from pathlib import Path

import pytest
from sqlalchemy import create_engine

from triage.config import SourceMapping
from triage.db import build_select

ROOT = Path(__file__).resolve().parent.parent


def test_default_mapping_loads():
    m = SourceMapping.load(ROOT / "config" / "source.yaml")
    assert m.table == "tickets"
    assert m.columns["body"] == "body"


def test_mapping_requires_core_fields(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text("table: t\ncolumns:\n  id: ticket_no\n  subject: title\n")
    with pytest.raises(ValueError, match="body"):
        SourceMapping.load(p)


def test_select_renames_columns_and_nulls_missing_ones():
    engine = create_engine("postgresql+psycopg://u:p@localhost/db")
    m = SourceMapping(
        table="support.cases",
        columns={"id": "case_no", "subject": "Title", "body": "description", "channel": None},
    )
    sql = build_select(engine, m)
    assert 'case_no AS id' in sql
    assert '"Title" AS subject' in sql
    assert "NULL AS channel" in sql
    assert "NULL AS customer" in sql
    assert sql.endswith("FROM support.cases")
