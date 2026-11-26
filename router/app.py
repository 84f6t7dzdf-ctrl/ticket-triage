"""Streamlit app: route support tickets to queues and flag urgent ones."""
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from assumptions import CONFIDENCE_THRESHOLD, QUEUES
from logic import REVIEW, classify_all, evaluate, threshold_sweep

SAMPLE = Path(__file__).parent / "sample_tickets.csv"
REQUIRED = {"subject", "body"}

st.set_page_config(page_title="Ticket router", layout="wide")
st.title("Ticket router")


def get_api_key() -> str | None:
    try:
        if "ANTHROPIC_API_KEY" in st.secrets:
            return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_API_KEY")


@st.cache_data(show_spinner=False)
def llm_route(subject: str, body: str, tier: str) -> dict | None:
    """One Claude call per distinct ticket, cached across reruns."""
    from llm import classify_with_llm, make_client

    return classify_with_llm({"subject": subject, "body": body, "tier": tier}, make_client(get_api_key()))


# ---- controls ---------------------------------------------------------
with st.sidebar:
    st.header("Settings")
    threshold = st.slider(
        "Confidence threshold", 0.0, 1.0, CONFIDENCE_THRESHOLD, 0.05,
        help="Tickets whose top queue has less than this share of keyword hits go to Review.",
    )
    st.caption("Higher means fewer mistakes, but more tickets for a person to route.")
    api_key = get_api_key()
    use_llm = st.toggle("Send the review pile to Claude", value=False, disabled=not api_key)
    if not api_key:
        st.caption("Add ANTHROPIC_API_KEY to the app's secrets to enable this.")

upload = st.file_uploader("Upload a CSV of tickets (columns: subject, body, and optionally tier)", type="csv")
df = pd.read_csv(upload) if upload else pd.read_csv(SAMPLE)
st.caption(f"Using {'uploaded file' if upload else 'sample tickets'}: {len(df)} tickets.")

missing = REQUIRED - set(df.columns)
if missing:
    st.error(f"The CSV is missing required columns: {', '.join(sorted(missing))}")
    st.stop()

llm = None
if use_llm:
    def llm(ticket):
        return llm_route(str(ticket.get("subject") or ""), str(ticket.get("body") or ""), str(ticket.get("tier") or ""))

with st.spinner("Asking Claude about the review pile..." if use_llm else "Routing..."):
    try:
        results = classify_all(df, threshold, llm)
    except Exception as exc:
        st.error(f"Claude call failed, showing rules only: {exc}")
        results = classify_all(df, threshold)

# ---- trade-off --------------------------------------------------------
st.subheader("Threshold trade-off (rules only)")
sweep = threshold_sweep(df)
st.line_chart(sweep)
here = sweep.loc[round(round(threshold / 0.05) * 0.05, 2)]
msg = f"At {threshold:.2f}, the rules send {here['sent to Review']:.0%} of tickets to Review"
if "queue accuracy" in sweep.columns and pd.notna(here["queue accuracy"]):
    msg += f" and get {here['queue accuracy']:.0%} of the rest right"
st.caption(msg + ".")

# ---- results ----------------------------------------------------------
st.subheader("Tickets per queue")
counts = results["queue"].value_counts().reindex(QUEUES + [REVIEW], fill_value=0)
cols = st.columns(len(counts))
for col, (queue, n) in zip(cols, counts.items()):
    col.metric(queue, int(n))
n_llm = int((results["decided_by"] == "llm").sum())
if use_llm:
    st.caption(f"Claude routed {n_llm} ticket(s) from the review pile.")

show = [c for c in ["id", "subject", "tier", "queue", "urgent", "confidence", "decided_by", "reason"]
        if c in results.columns]

st.subheader(f"Urgent ({int(results['urgent'].sum())})")
st.dataframe(results.loc[results["urgent"], show], hide_index=True, width="stretch")

st.subheader(f"Review pile ({int((results['queue'] == REVIEW).sum())})")
st.dataframe(results.loc[results["queue"] == REVIEW, show], hide_index=True, width="stretch")

st.subheader("All results")
st.dataframe(results[show + [c for c in ["true_queue", "true_urgent"] if c in results.columns]],
             hide_index=True, width="stretch")

if {"true_queue", "true_urgent"} <= set(results.columns):
    st.subheader("Accuracy against labels")
    ev = evaluate(results)
    a, b, c = st.columns(3)
    a.metric("Queue accuracy", "n/a" if ev["queue_accuracy"] is None else f"{ev['queue_accuracy']:.0%}")
    b.metric("Urgent accuracy", "n/a" if ev["urgent_accuracy"] is None else f"{ev['urgent_accuracy']:.0%}")
    c.metric("Sent to Review", ev["review_count"])
    st.caption(f"Accuracy covers the {ev['decided']} tickets not sent to Review.")
    if n_llm:
        decided = results[results["queue"] != REVIEW]
        by = pd.DataFrame([
            {"decided by": src, "tickets": len(g), "queue accuracy": f"{(g['queue'] == g['true_queue']).mean():.0%}"}
            for src, g in decided.groupby("decided_by")
        ])
        st.dataframe(by, hide_index=True, width="stretch")
    st.dataframe(ev["confusion"], width="stretch")
