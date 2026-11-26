"""Streamlit entry point. Step 1 only checks the connection and lists tickets;
the triage queue, detail view and metrics arrive in step 4."""
import pandas as pd
import streamlit as st

from triage.config import Settings
from triage.db import TicketStore

st.set_page_config(page_title="Ticket triage", layout="wide")
st.title("Ticket triage")


@st.cache_resource
def get_store() -> TicketStore:
    return TicketStore(Settings.load())


try:
    store = get_store()
    total = store.count_tickets()
except Exception as exc:  # show setup problems in the UI rather than a stack trace
    st.error(f"Could not connect to the ticket database: {exc}")
    st.info("Check DATABASE_URL in .env or .streamlit/secrets.toml, then run `python scripts/seed.py`.")
    st.stop()

st.success(f"Connected. {total} tickets in `{store.settings.source.table}`.")
tickets = store.fetch_tickets(limit=500)
st.dataframe(
    pd.DataFrame([t.__dict__ for t in tickets]),
    width="stretch",
    hide_index=True,
)
