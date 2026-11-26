"""Rules engine: keyword/pattern scoring driven by config/rules.yaml.

For each ticket it decides a queue, a ticket type and a priority, flags
named VIPs, and returns a confidence score plus the names of the rules
that fired, so every decision can be explained. Low-confidence tickets
are the ones handed to Claude in step 3.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import REPO_ROOT, load_vip_customers
from .db import Ticket, TriageResult

STANDARD = "standard"


@dataclass(frozen=True)
class Rule:
    name: str
    weight: float
    regex: re.Pattern
    priority: str | None = None


def _compile(items: list[dict]) -> list[Rule]:
    return [
        Rule(i["name"], float(i.get("weight", 1)), re.compile(i["pattern"], re.IGNORECASE), i.get("priority"))
        for i in items
    ]


def _score(rules: list[Rule], text: str) -> tuple[float, list[str]]:
    hits = [r for r in rules if r.regex.search(text)]
    return sum(r.weight for r in hits), [r.name for r in hits]


def _bump(priority: str) -> str:
    return f"P{max(1, int(priority[1]) - 1)}"


def _margin_confidence(best: float, runner_up: float, saturate: float = 4.0) -> float:
    """0..1. High when the winner scored well and clearly beat the runner-up."""
    if best <= 0:
        return 0.0
    strength = min(1.0, best / saturate)
    separation = (best - runner_up) / best
    return round(strength * (0.4 + 0.6 * separation), 3)


class RulesEngine:
    def __init__(self, config: dict, vip_customers: set[str]):
        self.llm_threshold = float(config.get("llm_threshold", 0.6))
        self.types = {
            name: {
                "queue": spec["queue"],
                "priority": spec["priority"],
                "min_score": float(spec.get("min_score", 1)),
                "rules": _compile(spec["patterns"]),
            }
            for name, spec in config["ticket_types"].items()
        }
        self.queues = {name: _compile(spec["patterns"]) for name, spec in config["queues"].items()}
        p = config["priority"]
        self.default_priority = p["default_by_queue"]
        self.priority_overrides = [
            (o["name"], o["priority"], re.compile(o["pattern"], re.IGNORECASE)) for o in p.get("overrides", [])
        ]
        self.bump_vip = bool(p.get("bump_vip", True))
        self.bump_enterprise_except = set(p.get("bump_enterprise_except", ["P4"]))
        self.vips = vip_customers

    @classmethod
    def load(cls, rules_path: str | Path = "config/rules.yaml",
             vip_path: str | Path = "config/vip_customers.yaml") -> "RulesEngine":
        rules_path = Path(rules_path)
        if not rules_path.is_absolute():
            rules_path = REPO_ROOT / rules_path
        return cls(yaml.safe_load(rules_path.read_text()), load_vip_customers(vip_path))

    def classify(self, ticket: Ticket) -> TriageResult:
        text = f"{ticket.subject}\n{ticket.body}"
        fired: list[str] = []
        notes: list[str] = []

        # 1. Special ticket types: outage, security, payment_failed, cant_login.
        type_scores = {}
        for name, spec in self.types.items():
            score, hits = _score(spec["rules"], text)
            if score >= spec["min_score"]:
                type_scores[name] = (score, hits)
        ranked_types = sorted(type_scores.items(), key=lambda kv: kv[1][0], reverse=True)

        # 2. Queue scores, always computed: they confirm or contradict the type.
        queue_scores = {q: _score(rules, text) for q, rules in self.queues.items()}
        ranked_queues = sorted(queue_scores.items(), key=lambda kv: kv[1][0], reverse=True)

        if ranked_types:
            ticket_type, (best, hits) = ranked_types[0]
            runner_up = ranked_types[1][1][0] if len(ranked_types) > 1 else 0.0
            spec = self.types[ticket_type]
            queue, priority = spec["queue"], spec["priority"]
            rule_priorities = [r.priority for r in spec["rules"] if r.name in hits]
            if rule_priorities and all(rule_priorities):
                priority = min(rule_priorities)  # "P1" < "P2": most urgent
            fired += [f"{ticket_type}:{h}" for h in hits]
            confidence = _margin_confidence(best, runner_up)
            notes.append(f"Matched {ticket_type} (score {best:g}).")
            if runner_up:
                notes.append(f"Also looked like {ranked_types[1][0]} (score {runner_up:g}).")
            # A strong signal for a different queue means two issues in one ticket.
            other = [(q, s) for q, (s, _) in ranked_queues if q != queue and s >= 3]
            if other:
                confidence = round(confidence * 0.7, 3)
                notes.append(f"Also mentions {other[0][0]} topics.")
        else:
            ticket_type = STANDARD
            queue, (best, hits) = ranked_queues[0]
            runner_up = ranked_queues[1][1][0]
            if best == 0:
                queue = "General"
                confidence = 0.1
                notes.append("No rule matched; defaulted to General.")
            else:
                fired += [f"{queue}:{h}" for h in hits]
                confidence = _margin_confidence(best, runner_up)
                notes.append(f"Queue {queue} (score {best:g}, next best {runner_up:g}).")
            priority = self.default_priority.get(queue, "P3")
            for name, level, regex in self.priority_overrides:
                if regex.search(text):
                    priority = level
                    fired.append(f"priority:{name}")
                    break

        # 3. Escalations.
        is_vip = (ticket.customer or "").strip().lower() in self.vips
        if is_vip and self.bump_vip:
            priority = _bump(priority)
            fired.append("escalate:vip")
            notes.append("Named VIP customer.")
        elif (ticket.customer_tier or "").lower() == "enterprise" and priority not in self.bump_enterprise_except:
            priority = _bump(priority)
            fired.append("escalate:enterprise")

        return TriageResult(
            ticket_id=ticket.id,
            queue=queue,
            ticket_type=ticket_type,
            priority=priority,
            confidence=confidence,
            decided_by="rules",
            reasoning=" ".join(notes),
            rules_fired=fired,
            is_vip=is_vip,
        )

    def needs_llm(self, result: TriageResult) -> bool:
        return result.confidence < self.llm_threshold
