"""Claude fallback for tickets the keyword rules can't route confidently.

Only tickets in the Review pile are sent. Claude must answer in a fixed
JSON shape (structured outputs), with the queue limited to QUEUES.
"""
from __future__ import annotations

import json

import anthropic

from assumptions import QUEUES

MODEL = "claude-opus-5-5"

SYSTEM = (
    "You route customer support tickets for a software company. "
    f"Pick exactly one queue from: {', '.join(QUEUES)}. "
    "Billing: invoices, charges, refunds, payments. "
    "Technical: errors, bugs, outages, slowness, data problems. "
    "Account: logins, passwords, access, permissions, security. "
    "Sales: pricing, plans, seats, upgrades, contracts, demos. "
    "General: how-to questions, feedback, feature ideas, anything else. "
    "If a ticket mentions several issues, choose the queue that must act first "
    "to unblock the customer. Mark urgent if the customer is blocked, losing "
    "money or data, facing a security risk, or under a deadline. "
    "Give a one-sentence reason a support lead can check."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "queue": {"type": "string", "enum": QUEUES},
        "urgent": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["queue", "urgent", "reason"],
    "additionalProperties": False,
}


def make_client(api_key: str | None = None) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()


def classify_with_llm(ticket: dict, client: anthropic.Anthropic) -> dict | None:
    """Ask Claude to route one ticket. Returns queue, urgent and reason, or
    None if Claude declined, so the ticket stays in Review."""
    text = (
        f"Subject: {ticket.get('subject') or ''}\n"
        f"Body: {ticket.get('body') or ''}\n"
        f"Customer tier: {ticket.get('tier') or 'unknown'}"
    )
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM,
        messages=[{"role": "user", "content": text}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        # If a safety classifier declines, the API retries on a fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        return None
    block = next((b for b in response.content if b.type == "text"), None)
    if block is None:
        return None
    answer = json.loads(block.text)
    if answer.get("queue") not in QUEUES:
        return None
    return answer
