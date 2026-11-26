import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from logic import REVIEW, classify, evaluate  # noqa: E402


def test_clear_billing_ticket():
    r = classify({"subject": "Refund for duplicate charge",
                  "body": "We were charged twice on our last invoice.", "tier": "Pro"})
    assert r["queue"] == "Billing"
    assert r["confidence"] == 1.0
    assert r["urgent"] is False
    assert "refund" in r["reason"] and "invoice" in r["reason"]


def test_urgent_vip_ticket():
    r = classify({"subject": "Login broken", "body": "Nobody on the team can log in.", "tier": "Enterprise"})
    assert r["urgent"] is True
    assert "VIP tier" in r["reason"]
    # An urgent word flags urgency even without a VIP tier.
    assert classify({"subject": "Please help ASAP", "body": "", "tier": "Free"})["urgent"] is True


def test_no_match_goes_to_review():
    r = classify({"subject": "Following up", "body": "Still waiting to hear back.", "tier": "Pro"})
    assert r["queue"] == REVIEW
    assert r["confidence"] == 0
    assert r["reason"].startswith("No keywords matched")


def test_evaluate_three_rows():
    df = pd.DataFrame({
        "queue":       ["Billing", "Technical", REVIEW],
        "urgent":      [False, True, True],
        "true_queue":  ["Billing", "Account", "Sales"],
        "true_urgent": [False, False, True],
    })
    ev = evaluate(df)
    # Review row is excluded: 2 decided rows. Queue: 1 of 2 right. Urgent: 1 of 2 right.
    assert ev["decided"] == 2
    assert ev["review_count"] == 1
    assert ev["queue_accuracy"] == pytest.approx(0.5)
    assert ev["urgent_accuracy"] == pytest.approx(0.5)
    assert ev["confusion"].loc["Sales", REVIEW] == 1
    assert ev["confusion"].loc["Account", "Technical"] == 1


def test_threshold_controls_review():
    ticket = {"subject": "Error on the invoice page", "body": "", "tier": "Free"}  # 50/50 split
    assert classify(ticket, threshold=0.6)["queue"] == REVIEW
    assert classify(ticket, threshold=0.5)["queue"] in ("Billing", "Technical")
    # No keyword hits stays in Review even at threshold 0.
    assert classify({"subject": "Following up", "body": ""}, threshold=0.0)["queue"] == REVIEW


def test_llm_fallback_only_for_review_pile():
    from logic import classify_all
    calls = []

    def fake_llm(ticket):
        calls.append(ticket["subject"])
        return {"queue": "Technical", "urgent": False, "reason": "invoice page error is a bug"}

    df = pd.DataFrame({
        "subject": ["Refund for invoice", "Error on the invoice page", "Following up"],
        "body": ["", "", ""],
        "tier": ["Pro", "Free", "Enterprise"],
    })
    out = classify_all(df, 0.6, fake_llm)
    assert calls == ["Error on the invoice page", "Following up"]
    assert list(out["decided_by"]) == ["rules", "llm", "llm"]
    assert out.loc[1, "queue"] == "Technical"
    assert out.loc[2, "urgent"]  # VIP urgency from the rules is kept


def test_llm_decline_leaves_ticket_in_review():
    from logic import classify_all
    df = pd.DataFrame({"subject": ["Following up"], "body": [""], "tier": ["Pro"]})
    out = classify_all(df, 0.6, lambda t: None)
    assert out.loc[0, "queue"] == REVIEW and out.loc[0, "decided_by"] == "rules"


def test_llm_parses_structured_answer():
    from types import SimpleNamespace
    from llm import classify_with_llm

    class FakeMessages:
        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(stop_reason="end_turn", content=[
                SimpleNamespace(type="text", text='{"queue": "Account", "urgent": true, "reason": "Blocked from logging in."}')])

    msgs = FakeMessages()
    client = SimpleNamespace(beta=SimpleNamespace(messages=msgs))
    answer = classify_with_llm({"subject": "Paid but can't get in", "body": "", "tier": "Pro"}, client)
    assert answer == {"queue": "Account", "urgent": True, "reason": "Blocked from logging in."}
    assert msgs.kwargs["output_config"]["format"]["schema"]["properties"]["queue"]["enum"][0] == "Billing"
