import importlib.util
from collections import Counter
from pathlib import Path

from triage.config import load_vip_customers

spec = importlib.util.spec_from_file_location("seed", Path(__file__).resolve().parent.parent / "scripts" / "seed.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def test_generated_tickets_cover_every_queue_and_type():
    tickets = seed.generate(200)
    assert len(tickets) == 200
    assert set(t["queue"] for t in tickets) == set(seed.QUEUES)
    assert set(t["ticket_type"] for t in tickets) == set(seed.TICKET_TYPES)
    assert set(t["customer_tier"] for t in tickets) == set(seed.TIERS)
    assert any(t["is_vip"] for t in tickets)


def test_vips_match_config_and_are_never_low_priority():
    vips = load_vip_customers()
    for t in seed.generate(200):
        assert t["is_vip"] == (t["customer"].lower() in vips)
        if t["is_vip"]:
            assert t["priority"] in ("P1", "P2", "P3")


def test_generation_is_deterministic():
    assert seed.generate(50) == seed.generate(50)


def test_special_types_are_a_minority():
    counts = Counter(t["ticket_type"] for t in seed.generate(1000))
    assert 0.55 < counts["standard"] / 1000 < 0.85
