import pytest

from triage.db import Ticket
from triage.rules import RulesEngine


@pytest.fixture(scope="module")
def engine():
    return RulesEngine.load()


def t(subject, body, customer="Acme Logistics", tier="business"):
    return Ticket(id="1", subject=subject, body=body, customer=customer, customer_tier=tier, channel="email")


@pytest.mark.parametrize("subject,body,queue,ticket_type,priority", [
    ("Everything is down", "Our whole team gets a 503, the platform is down.", "Technical", "outage", "P1"),
    ("Account compromised?", "We think our admin account was hacked last night.", "Account", "security", "P1"),
    ("Payment failed", "Your system says our payment failed but the card is fine.", "Billing", "payment_failed", "P2"),
    ("Can't sign in", "I can't log in since this morning, invalid password every time.", "Account", "cant_login", "P2"),
    ("Refund please", "We were charged for a month we didn't use. Please refund.", "Billing", "standard", "P3"),
    ("Pricing", "Can you send a quote for 40 more seats?", "Sales", "standard", "P3"),
    ("Feature request", "Would be great to have keyboard shortcuts.", "General", "standard", "P4"),
    ("Crash", "The app crashes when I open settings.", "Technical", "standard", "P2"),
])
def test_clear_tickets(engine, subject, body, queue, ticket_type, priority):
    r = engine.classify(t(subject, body))
    assert (r.queue, r.ticket_type, r.priority) == (queue, ticket_type, priority), r.reasoning
    assert not engine.needs_llm(r), f"confidence {r.confidence}"
    assert r.rules_fired and r.decided_by == "rules"


def test_vip_is_flagged_and_escalated(engine):
    r = engine.classify(t("Feature request", "Would be great to have keyboard shortcuts.", customer="Meridian Bank", tier="enterprise"))
    assert r.is_vip and r.priority == "P3"
    assert "escalate:vip" in r.rules_fired


def test_enterprise_escalates_except_p4(engine):
    assert engine.classify(t("Refund", "We were charged twice, refund please.", tier="enterprise")).priority == "P2"
    assert engine.classify(t("Idea", "Would be nice to have dark mode.", tier="enterprise")).priority == "P4"


def test_phishing_is_security_but_p2(engine):
    r = engine.classify(t("Phishing", "Staff got a phishing email pretending to be you."))
    assert (r.ticket_type, r.priority) == ("security", "P2")


@pytest.mark.parametrize("subject,body", [
    ("Problem", "It doesn't work. Please fix."),
    ("Hmm", "Following up again on this."),
    ("Two things", "We were charged twice, and also the export throws an error."),
])
def test_vague_or_mixed_tickets_go_to_llm(engine, subject, body):
    assert engine.needs_llm(engine.classify(t(subject, body)))


def test_no_match_defaults_to_general_with_low_confidence(engine):
    r = engine.classify(t("Hello", "Bonjour, rien ne marche."))
    assert r.queue == "General" and r.confidence < 0.2
