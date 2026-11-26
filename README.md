# Ticket triage

A prototype that triages support tickets: a rules engine handles the clear-cut
cases, and Claude handles the tricky ones. Tickets are read from a Postgres
database and results are shown in a Streamlit app.

## Status

| Step | What | State |
|---|---|---|
| 1 | Ticket database, synthetic data, database adapter, repo skeleton | done |
| 2 | Rules engine (queue, ticket type, priority, VIP flag, confidence) | next |
| 3 | Claude for low-confidence tickets | |
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
config/source.yaml     Maps the source table's columns onto ticket fields
config/vip_customers.yaml  Named VIP customers
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
