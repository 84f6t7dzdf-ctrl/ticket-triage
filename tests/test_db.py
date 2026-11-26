"""Integration tests. They need a seeded database at DATABASE_URL and are
skipped if it can't be reached."""
import pytest
from sqlalchemy import text

from triage.config import Settings
from triage.db import TicketStore, TriageResult


@pytest.fixture(scope="module")
def store():
    try:
        s = TicketStore(Settings.load())
        s.count_tickets()
    except Exception as exc:
        pytest.skip(f"database not available: {exc}")
    return s


def test_tickets_are_seeded(store):
    assert store.count_tickets() >= 100
    tickets = store.fetch_tickets(limit=5)
    assert len(tickets) == 5
    assert all(t.subject and t.body for t in tickets)
    assert isinstance(tickets[0].id, str)


def test_results_round_trip(store):
    ticket = store.fetch_tickets(limit=1)[0]
    store.save_results([
        TriageResult(ticket.id, "bug", "P3", "Engineering", 0.4, "rules", rules_fired=["kw:error"]),
        TriageResult(ticket.id, "bug", "P2", "Engineering", 0.9, "llm", reasoning="mentions a crash"),
    ])
    try:
        latest = store.latest_results()[ticket.id]
        assert latest.decided_by == "llm"
        assert latest.priority == "P2"
    finally:
        with store.results.begin() as conn:
            conn.execute(text("DELETE FROM triage_results WHERE ticket_id = :id"), {"id": ticket.id})
