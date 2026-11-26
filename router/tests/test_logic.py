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
