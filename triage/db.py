"""The only module that talks to databases.

Reads tickets from the source database through the column mapping in
config/source.yaml, and reads and writes triage results in the results
database. To point the app at a different database, change DATABASE_URL
and the mapping; nothing else should need to change.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import OPTIONAL_FIELDS, REQUIRED_FIELDS, Settings, SourceMapping


@dataclass
class Ticket:
    id: str
    subject: str
    body: str
    customer: str | None = None
    customer_tier: str | None = None
    channel: str | None = None
    created_at: datetime | None = None


@dataclass
class TriageResult:
    ticket_id: str
    queue: str  # Billing | Technical | Account | Sales | General
    ticket_type: str  # outage | cant_login | security | payment_failed | standard
    priority: str  # P1..P4
    confidence: float
    decided_by: str  # rules | llm | human
    reasoning: str | None = None
    rules_fired: list[str] = field(default_factory=list)
    is_vip: bool = False
    created_at: datetime | None = None


def _quote(engine: Engine, name: str) -> str:
    """Quote an identifier (optionally schema-qualified) for this dialect."""
    preparer = engine.dialect.identifier_preparer
    return ".".join(preparer.quote(part) for part in name.split("."))


def build_select(engine: Engine, mapping: SourceMapping) -> str:
    """SELECT that renames the source columns to the app's field names."""
    parts = []
    for name in REQUIRED_FIELDS + OPTIONAL_FIELDS:
        col = mapping.columns.get(name)
        expr = _quote(engine, col) if col else "NULL"
        parts.append(f"{expr} AS {name}")
    return f"SELECT {', '.join(parts)} FROM {_quote(engine, mapping.table)}"


class TicketStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.source = create_engine(settings.database_url, pool_pre_ping=True)
        if settings.results_database_url == settings.database_url:
            self.results = self.source
        else:
            self.results = create_engine(settings.results_database_url, pool_pre_ping=True)

    # ---- source -------------------------------------------------------
    def fetch_tickets(self, limit: int | None = None) -> list[Ticket]:
        sql = build_select(self.source, self.settings.source)
        id_col = self.settings.source.columns["id"]
        sql += f" ORDER BY {_quote(self.source, id_col)}"
        params = {}
        if limit is not None:
            sql += " LIMIT :limit"
            params["limit"] = limit
        with self.source.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return [
            Ticket(**{**row, "id": str(row["id"])})
            for row in rows
        ]

    def count_tickets(self) -> int:
        table = _quote(self.source, self.settings.source.table)
        with self.source.connect() as conn:
            return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()

    # ---- results ------------------------------------------------------
    def save_results(self, results: Iterable[TriageResult]) -> int:
        rows = [
            {
                "ticket_id": r.ticket_id,
                "queue": r.queue,
                "ticket_type": r.ticket_type,
                "priority": r.priority,
                "is_vip": r.is_vip,
                "confidence": r.confidence,
                "decided_by": r.decided_by,
                "reasoning": r.reasoning,
                "rules_fired": json.dumps(r.rules_fired),
            }
            for r in results
        ]
        if not rows:
            return 0
        sql = text(
            "INSERT INTO triage_results "
            "(ticket_id, queue, ticket_type, priority, is_vip, confidence, decided_by, reasoning, rules_fired) "
            "VALUES (:ticket_id, :queue, :ticket_type, :priority, :is_vip, :confidence, :decided_by, "
            ":reasoning, CAST(:rules_fired AS JSONB))"
        )
        with self.results.begin() as conn:
            conn.execute(sql, rows)
        return len(rows)

    def latest_results(self) -> dict[str, TriageResult]:
        """Most recent triage decision per ticket, keyed by ticket id."""
        sql = text(
            "SELECT DISTINCT ON (ticket_id) ticket_id, queue, ticket_type, priority, is_vip, "
            "confidence, decided_by, reasoning, rules_fired, created_at "
            "FROM triage_results ORDER BY ticket_id, created_at DESC, id DESC"
        )
        with self.results.connect() as conn:
            rows = conn.execute(sql).mappings().all()
        return {row["ticket_id"]: TriageResult(**row) for row in rows}

    def clear_results(self) -> None:
        with self.results.begin() as conn:
            conn.execute(text("DELETE FROM triage_results"))
