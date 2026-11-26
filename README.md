# Ticket triage

A prototype that triages support tickets: a rules engine handles the clear-cut
cases, and Claude handles the tricky ones. Tickets are read from a Postgres
database and results are shown in a Streamlit app.

## Status

| Step | What | State |
|---|---|---|
| 1 | Ticket database, synthetic data, database adapter, repo skeleton | done |
| 2 | Rules engine (queue, ticket type, priority, VIP flag, confidence) | done |
| 3 | Claude for low-confidence tickets | next |
| 4 | Streamlit triage queue, detail view, metrics | |

## Quick start

Needs Python 3.11+ and Docker.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

docker compose up -d --wait     # Postgres 16 on localhost:5432
python scripts/seed.py          # 200 synthetic tickets
pytest                          # unit + database tests
streamlit run app.py
```

`python scripts/seed.py --reset` drops and recreates the tables, then re-seeds. `-n 500` changes the count.

No Docker? Any Postgres works (a local install, Neon, Supabase): create a
database, set `DATABASE_URL` in `.env`, and run the seed script, which also
creates the tables.

## Layout

```
app.py                 Streamlit entry point
triage/config.py       Settings from .env / Streamlit secrets, column mapping
triage/db.py           The only code that touches the database
triage/rules.py        Rules engine
config/source.yaml     Maps the source table's columns onto ticket fields
config/vip_customers.yaml  Named VIP customers
config/rules.yaml      Triage rules (patterns, weights, priorities, LLM threshold)
scripts/evaluate.py    Accuracy report for the rules against the labels
db/schema.sql          tickets, ticket_labels, triage_results
scripts/seed.py        Synthetic ticket generator
tests/                 pytest (database tests skip if no DB is reachable)
```

## Data model

Each ticket has a **subject**, **body**, **customer**, **customer tier**
(enterprise, business or starter) and **channel** (email, web, chat or phone).
Triage gives it three things:

| Output | Values |
|---|---|
| Queue | Billing, Technical, Account, Sales, General |
| Ticket type | `outage`, `cant_login`, `security`, `payment_failed`, or `standard` for everything else |
| Priority | P1 (most urgent) to P4 |

On top of that, any ticket from a named VIP customer is flagged as VIP. The VIP
list lives in `config/vip_customers.yaml`. VIP is a flag rather than a ticket
type, because a VIP can also have an outage or a failed payment.

Tables:

- **tickets**: the source data.
- **ticket_labels**: the correct queue, type, priority and VIP flag for each
  synthetic ticket, plus an `is_ambiguous` flag. Only used to measure accuracy.
  A real source database won't have it and the app doesn't need it.
- **triage_results**: one row per decision, with `decided_by` (`rules`, `llm`
  or `human`), confidence, reasoning and the rules that fired. The app shows
  the latest row per ticket.

How the synthetic data is built:

- Each customer has a fixed tier, and the three VIPs are enterprise accounts.
- Priority starts from the kind of issue. Outages and most security tickets
  are P1, failed payments and login problems P2, and how-to questions and
  feature requests P4. VIP tickets go up one level, and other enterprise
  tickets go up one level unless they're P4.
- About 70% of tickets are `standard` and the rest are split across the four
  special types.
- About 15% are deliberately ambiguous: two issues in one ticket, vague
  wording, or a message in French. These are the ones the LLM should pick up.

## Rules engine

`triage/rules.py` reads `config/rules.yaml` and, for each ticket:

1. Scores the four special ticket types (outage, security, payment_failed,
   cant_login). Each pattern that matches adds its weight. The highest score
   above the type's `min_score` wins, and that type fixes the queue and the
   base priority.
2. Otherwise the ticket is `standard`, and the queue patterns pick a queue.
   The base priority comes from the queue, adjusted by keyword overrides
   such as "error 500" (P2) or "not urgent" (P4).
3. Escalates: named VIPs go up one priority level, and enterprise tickets go
   up one level unless they're P4.
4. Gives a **confidence** from 0 to 1, based on how strongly the winner scored
   and how far ahead of the runner-up it was. Mixed signals, such as a
   security ticket that also talks about invoices, lower it. Tickets below
   `llm_threshold` (0.6) are the ones Claude will handle in step 3.

Every result lists the rules that fired and a one-line reason, so you can
explain any decision.

```bash
python scripts/evaluate.py            # accuracy against the labels
python scripts/evaluate.py --errors   # list each mistake and whether Claude would catch it
python scripts/evaluate.py --save     # write the results to triage_results
```

Results on the 200 seeded tickets:

| | |
|---|---|
| Decided by rules | 64.5% (129 tickets), all four fields correct on every one |
| Sent to Claude | 35.5% (71 tickets), including all 30 ambiguous ones |
| Rules accuracy if forced to decide everything | 87.5% |

Take the 100% with a pinch of salt: the rules were tuned against this
synthetic data, so they'll do worse on real tickets. That's what the
confidence threshold is for, and `tests/test_rules.py` checks the rules
against freshly written tickets that aren't in the seed data.

## Connecting to a different database

Everything goes through `triage/db.py`, so switching databases is config only:

1. Set `DATABASE_URL` to the new database. Any SQLAlchemy URL works, for
   example `postgresql+psycopg://user:pass@host:5432/dbname`.
2. If its ticket table looks different, edit `config/source.yaml` (or point
   `SOURCE_CONFIG` at a copy). `id`, `subject` and `body` are required, and
   optional columns can be `null`:

   ```yaml
   table: support.cases
   columns:
     id: case_number
     subject: title
     body: description
     customer: account_name
     customer_tier: plan
     channel: null
     created_at: opened_at
   ```
3. If the source is read-only, set `RESULTS_DATABASE_URL` to a database you
   can write to and run `db/schema.sql` there to create `triage_results`.
