"""Settings, read from env vars, a .env file, or Streamlit secrets."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_FIELDS = ("id", "subject", "body")
OPTIONAL_FIELDS = ("customer", "channel", "created_at")

load_dotenv(REPO_ROOT / ".env")


def _get(name: str, default: str | None = None) -> str | None:
    """Env var first, then Streamlit secrets (if running under Streamlit)."""
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return default


@dataclass(frozen=True)
class SourceMapping:
    """How the source database's columns map onto the app's ticket fields."""

    table: str
    columns: dict[str, str | None]

    @classmethod
    def load(cls, path: str | Path) -> "SourceMapping":
        path = Path(path)
        if not path.is_absolute():
            path = REPO_ROOT / path
        data = yaml.safe_load(path.read_text())
        columns = data.get("columns") or {}
        missing = [f for f in REQUIRED_FIELDS if not columns.get(f)]
        if missing:
            raise ValueError(f"{path}: mapping is missing required fields {missing}")
        unknown = set(columns) - set(REQUIRED_FIELDS) - set(OPTIONAL_FIELDS)
        if unknown:
            raise ValueError(f"{path}: unknown fields {sorted(unknown)}")
        return cls(table=data["table"], columns=columns)


@dataclass(frozen=True)
class Settings:
    database_url: str
    results_database_url: str
    source: SourceMapping
    anthropic_api_key: str | None

    @classmethod
    def load(cls) -> "Settings":
        db_url = _get("DATABASE_URL")
        if not db_url:
            raise RuntimeError(
                "DATABASE_URL is not set. Copy .env.example to .env, "
                "or set it in .streamlit/secrets.toml."
            )
        return cls(
            database_url=db_url,
            results_database_url=_get("RESULTS_DATABASE_URL", db_url),
            source=SourceMapping.load(_get("SOURCE_CONFIG", "config/source.yaml")),
            anthropic_api_key=_get("ANTHROPIC_API_KEY"),
        )
