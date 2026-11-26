"""Routing logic. Pure functions, no Streamlit, so they're easy to test."""
from __future__ import annotations

import re

import pandas as pd

from assumptions import CONFIDENCE_THRESHOLD, KEYWORDS, URGENT_WORDS, VIP_TIERS

REVIEW = "Review"


def _found(word: str, text: str) -> bool:
    """Whole-word (or whole-phrase) match, case-insensitive."""
    return re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE) is not None


def classify(ticket: dict, threshold: float = CONFIDENCE_THRESHOLD) -> dict:
    """Route one ticket with the keyword rules.

    `ticket` needs subject and body, and may have tier. Below `threshold`
    the queue is Review. Returns a dict with queue, urgent, confidence,
    reason and decided_by ("rules").
    """
    subject = str(ticket.get("subject") or "")
    body = str(ticket.get("body") or "")
    tier = str(ticket.get("tier") or "")

    hits: dict[str, int] = {}
    matched: dict[str, list[str]] = {}
    for queue, words in KEYWORDS.items():
        for word in words:
            score = 2 * _found(word, subject) + _found(word, body)
            if score:
                hits[queue] = hits.get(queue, 0) + score
                matched.setdefault(queue, []).append(word)

    total = sum(hits.values())
    if total:
        top_queue = max(hits, key=hits.get)
        confidence = hits[top_queue] / total
    else:
        top_queue, confidence = None, 0.0

    # No hits at all always means Review, whatever the threshold.
    queue = top_queue if top_queue and confidence >= threshold else REVIEW

    urgent_words = [w for w in URGENT_WORDS if _found(w, subject) or _found(w, body)]
    is_vip = tier in VIP_TIERS
    urgent = bool(urgent_words) or is_vip

    if not total:
        reason = "No keywords matched."
    else:
        parts = [f"{q}: {', '.join(ws)} ({hits[q]})" for q, ws in matched.items()]
        reason = "Matched " + "; ".join(parts) + "."
        if queue == REVIEW:
            reason += f" Top queue {top_queue} only {confidence:.0%} of hits."
    if urgent_words:
        reason += f" Urgent words: {', '.join(urgent_words)}."
    if is_vip:
        reason += f" VIP tier: {tier}."

    return {"queue": queue, "urgent": urgent, "confidence": round(confidence, 2), "reason": reason,
            "decided_by": "rules"}


def classify_all(df: pd.DataFrame, threshold: float = CONFIDENCE_THRESHOLD, llm=None) -> pd.DataFrame:
    """Add queue, urgent, confidence, reason and decided_by columns.

    If `llm` is given, it is called for each ticket the rules send to Review.
    It takes the ticket dict and returns a dict with queue, urgent and reason
    (or None to leave the ticket in Review). Rule-based urgency is kept: a
    ticket stays urgent if either the rules or the LLM say so.
    """
    rows = []
    for ticket in df.to_dict("records"):
        result = classify(ticket, threshold)
        if llm is not None and result["queue"] == REVIEW:
            answer = llm(ticket)
            if answer:
                result = {
                    "queue": answer["queue"],
                    "urgent": result["urgent"] or bool(answer["urgent"]),
                    "confidence": result["confidence"],
                    "reason": f"Claude: {answer['reason']} (Rules: {result['reason']})",
                    "decided_by": "llm",
                }
        rows.append(result)
    return pd.concat([df, pd.DataFrame(rows, index=df.index)], axis=1)


def threshold_sweep(df: pd.DataFrame, steps: int = 21) -> pd.DataFrame:
    """Rules-only trade-off: for each threshold, the share of tickets sent to
    Review and (if labels exist) queue accuracy on the rest."""
    rows = []
    has_labels = "true_queue" in df.columns
    for i in range(steps):
        t = round(i / (steps - 1), 2)
        res = classify_all(df, t)
        decided = res[res["queue"] != REVIEW]
        row = {"threshold": t, "sent to Review": (res["queue"] == REVIEW).mean()}
        if has_labels:
            row["queue accuracy"] = (decided["queue"] == decided["true_queue"]).mean() if len(decided) else None
        rows.append(row)
    return pd.DataFrame(rows).set_index("threshold")


def evaluate(df: pd.DataFrame) -> dict:
    """Compare predictions with labels.

    `df` needs queue and urgent (predictions) and true_queue and true_urgent
    (labels). Rows sent to Review are left out of both accuracy figures and
    counted separately. The confusion table includes them.
    """
    decided = df[df["queue"] != REVIEW]
    n = len(decided)
    true_urgent = decided["true_urgent"].map(_to_bool)
    return {
        "queue_accuracy": float((decided["queue"] == decided["true_queue"]).mean()) if n else None,
        "urgent_accuracy": float((decided["urgent"].map(_to_bool) == true_urgent).mean()) if n else None,
        "decided": n,
        "review_count": int((df["queue"] == REVIEW).sum()),
        "confusion": pd.crosstab(df["true_queue"], df["queue"], rownames=["true"], colnames=["predicted"]),
    }


def _to_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1", "y")
    return bool(value)
