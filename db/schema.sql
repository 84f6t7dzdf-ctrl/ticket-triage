-- Source data: the tickets to triage.
-- In the exam this table may be replaced by someone else's database;
-- config/source.yaml maps their columns onto these names.
CREATE TABLE IF NOT EXISTS tickets (
    id          SERIAL PRIMARY KEY,
    subject     TEXT        NOT NULL,
    body        TEXT        NOT NULL,
    customer    TEXT,
    channel     TEXT,                      -- email | web | chat | phone
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ground-truth labels for the synthetic data only, used to measure
-- the accuracy of the rules engine and the LLM. A real source DB
-- will not have this table, and nothing in the app requires it.
CREATE TABLE IF NOT EXISTS ticket_labels (
    ticket_id   INTEGER PRIMARY KEY REFERENCES tickets(id) ON DELETE CASCADE,
    category    TEXT NOT NULL,
    priority    TEXT NOT NULL,
    team        TEXT NOT NULL,
    is_ambiguous BOOLEAN NOT NULL DEFAULT FALSE
);

-- Output: one row per triage decision. Kept separate from the source
-- so the source can stay read-only. ticket_id is TEXT so it can hold
-- any source system's id type.
CREATE TABLE IF NOT EXISTS triage_results (
    id           SERIAL PRIMARY KEY,
    ticket_id    TEXT        NOT NULL,
    category     TEXT        NOT NULL,
    priority     TEXT        NOT NULL,
    team         TEXT        NOT NULL,
    confidence   REAL        NOT NULL,
    decided_by   TEXT        NOT NULL CHECK (decided_by IN ('rules', 'llm', 'human')),
    reasoning    TEXT,
    rules_fired  JSONB       NOT NULL DEFAULT '[]'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_triage_results_ticket ON triage_results (ticket_id, created_at DESC);
