"""Run the rules engine over every ticket and compare with the labels.

    python scripts/evaluate.py            # print the accuracy report
    python scripts/evaluate.py --errors   # also list each wrong decision
    python scripts/evaluate.py --save     # also write results to triage_results

Needs the ticket_labels table, so it works on the synthetic data only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from triage.config import Settings  # noqa: E402
from triage.db import TicketStore  # noqa: E402
from triage.rules import RulesEngine  # noqa: E402

FIELDS = ("queue", "ticket_type", "priority", "is_vip")


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:5.1f}%  ({n}/{d})" if d else "   n/a"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--errors", action="store_true", help="list each wrong decision")
    parser.add_argument("--save", action="store_true", help="write results to triage_results")
    args = parser.parse_args()

    store = TicketStore(Settings.load())
    engine = RulesEngine.load()
    tickets = store.fetch_tickets()
    with store.source.connect() as conn:
        labels = {
            str(r["ticket_id"]): r
            for r in conn.execute(text("SELECT * FROM ticket_labels")).mappings()
        }

    rows = []
    for t in tickets:
        result = engine.classify(t)
        label = labels[t.id]
        correct = {f: getattr(result, f) == label[f] for f in FIELDS}
        rows.append((t, result, label, correct))

    def report(name: str, subset: list) -> None:
        n = len(subset)
        all_right = sum(all(c.values()) for *_, c in subset)
        print(f"\n{name} ({n} tickets)")
        for f in FIELDS:
            print(f"  {f:<12} {pct(sum(c[f] for *_, c in subset), n)}")
        print(f"  {'all four':<12} {pct(all_right, n)}")

    report("All tickets", rows)
    report("Clear tickets", [r for r in rows if not r[2]["is_ambiguous"]])
    report("Ambiguous tickets", [r for r in rows if r[2]["is_ambiguous"]])

    confident = [r for r in rows if not engine.needs_llm(r[1])]
    to_llm = [r for r in rows if engine.needs_llm(r[1])]
    print(f"\nRouting at llm_threshold={engine.llm_threshold}")
    print(f"  decided by rules  {pct(len(confident), len(rows))}")
    print(f"  sent to Claude    {pct(len(to_llm), len(rows))}")
    print(f"  rules accuracy on the tickets they keep (all four right): "
          f"{pct(sum(all(c.values()) for *_, c in confident), len(confident))}")
    amb = [r for r in rows if r[2]["is_ambiguous"]]
    print(f"  ambiguous tickets sent to Claude: {pct(sum(engine.needs_llm(r[1]) for r in amb), len(amb))}")

    if args.errors:
        print("\nWrong decisions (* = kept by rules, would not reach Claude):")
        for t, res, lab, c in rows:
            if all(c.values()):
                continue
            mark = "*" if not engine.needs_llm(res) else " "
            got = "/".join(str(getattr(res, f)) for f in FIELDS)
            want = "/".join(str(lab[f]) for f in FIELDS)
            print(f" {mark} #{t.id:<4} conf {res.confidence:.2f}  got {got:<38} want {want:<38} {t.subject}")

    if args.save:
        store.clear_results()
        store.save_results(r[1] for r in rows)
        print(f"\nSaved {len(rows)} results to triage_results.")


if __name__ == "__main__":
    main()
