"""Streamlit app: route support tickets to queues and flag urgent ones."""
from pathlib import Path

import pandas as pd
import streamlit as st

from assumptions import QUEUES
from logic import REVIEW, classify_all, evaluate

SAMPLE = Path(__file__).parent / "sample_tickets.csv"
REQUIRED = {"subject", "body"}

st.set_page_config(page_title="Ticket router", layout="wide")
st.title("Ticket router")

upload = st.file_uploader("Upload a CSV of tickets (columns: subject, body, and optionally tier)", type="csv")
df = pd.read_csv(upload) if upload else pd.read_csv(SAMPLE)
st.caption(f"Using {'uploaded file' if upload else 'sample tickets'}: {len(df)} tickets.")

missing = REQUIRED - set(df.columns)
if missing:
    st.error(f"The CSV is missing required columns: {', '.join(sorted(missing))}")
    st.stop()

results = classify_all(df)

st.subheader("Tickets per queue")
counts = results["queue"].value_counts().reindex(QUEUES + [REVIEW], fill_value=0)
cols = st.columns(len(counts))
for col, (queue, n) in zip(cols, counts.items()):
    col.metric(queue, int(n))

show = [c for c in ["id", "subject", "tier", "queue", "urgent", "confidence", "reason"] if c in results.columns]

st.subheader(f"Urgent ({int(results['urgent'].sum())})")
st.dataframe(results.loc[results["urgent"], show], hide_index=True, width="stretch")

st.subheader(f"Review pile ({int((results['queue'] == REVIEW).sum())})")
st.dataframe(results.loc[results["queue"] == REVIEW, show], hide_index=True, width="stretch")

st.subheader("All results")
st.dataframe(results[show + [c for c in ["true_queue", "true_urgent"] if c in results.columns]],
             hide_index=True, width="stretch")

if {"true_queue", "true_urgent"} <= set(results.columns):
    st.subheader("Accuracy against labels")
    ev = evaluate(results)
    a, b, c = st.columns(3)
    a.metric("Queue accuracy", "n/a" if ev["queue_accuracy"] is None else f"{ev['queue_accuracy']:.0%}")
    b.metric("Urgent accuracy", "n/a" if ev["urgent_accuracy"] is None else f"{ev['urgent_accuracy']:.0%}")
    c.metric("Sent to Review", ev["review_count"])
    st.caption(f"Accuracy covers the {ev['decided']} tickets not sent to Review.")
    st.dataframe(ev["confusion"], width="stretch")
