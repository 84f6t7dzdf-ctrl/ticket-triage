# Ticket router

A minimal Streamlit app that helps a support lead route incoming tickets to
the right queue and flag urgent ones. Keyword rules only, no database.

## Run it

```bash
cd router
pip install -r requirements.txt
streamlit run app.py
pytest
```

The app uses `sample_tickets.csv` until you upload your own CSV. A CSV needs
`subject` and `body` columns. `tier` is optional. If it also has `true_queue`
and `true_urgent`, the app shows accuracy against those labels.

## How it works

`logic.classify(ticket)`:

1. Counts keyword hits per queue (`KEYWORDS` in `assumptions.py`). A keyword
   in the subject counts 2, in the body 1. Matching is whole-word and
   case-insensitive.
2. Confidence is the top queue's hits divided by all hits, or 0 if nothing
   matched.
3. Below `CONFIDENCE_THRESHOLD` (0.6), the queue is `Review`, meaning a person
   routes it.
4. A ticket is urgent if it contains any of `URGENT_WORDS` or its tier is in
   `VIP_TIERS`.
5. The reason lists the words that matched for each queue, any urgent words
   and the VIP tier.

`logic.evaluate(df)` returns queue accuracy, urgent accuracy, how many tickets
went to Review and a confusion table. Review rows are left out of both
accuracy figures but appear in the confusion table.

All the numbers and word lists in `assumptions.py` are estimates. Tune them
there.

## Threshold slider

The sidebar slider sets the confidence threshold live (default 0.6 from
`assumptions.py`). The trade-off chart runs the rules at every threshold from
0 to 1 and plots two lines:

- **sent to Review**: the share of tickets a person has to route.
- **queue accuracy**: how many of the remaining tickets the rules get right
  (only when the CSV has `true_queue`).

Raising the threshold makes the rules more cautious: fewer mistakes, but a
bigger review pile. On the 20 sample tickets the lines move in steps, because
keyword splits are coarse (1.0, 0.5 or 0). A larger, messier CSV gives a
smoother curve.

## Claude fallback for the review pile

Switch on **Send the review pile to Claude** in the sidebar, and every ticket
the rules send to Review goes to Claude (`llm.py`). Claude picks one of the
five queues, says whether the ticket is urgent and gives a one-sentence
reason. Tickets the rules handled are never sent, so cost stays low.

- The toggle needs `ANTHROPIC_API_KEY`. On Streamlit Cloud, add it under
  **Manage app > Settings > Secrets** as `ANTHROPIC_API_KEY = "sk-ant-..."`.
  Locally, export it as an environment variable.
- Model: `claude-opus-5-5` at low effort, with structured outputs, so the
  answer is always valid JSON with a queue from the list.
- Rule-based urgency is kept: a VIP or urgent-word ticket stays urgent
  whatever Claude says.
- If Claude declines a ticket, it stays in Review. If a safety check declines
  it, the API retries on a fallback model automatically.
- Answers are cached per ticket, so moving the slider doesn't re-bill tickets
  already asked about.
- The results table has a `decided_by` column (`rules` or `llm`). With labels,
  the accuracy section shows accuracy separately for each.

## Sample data

20 tickets: 15 clear ones (3 per queue), 3 ambiguous ones that mention two
queues (16 to 18), and 2 that match no keyword (19 and 20). On the sample, the
15 clear tickets are all routed correctly and the other 5 go to Review. Ticket
16 is urgent but not flagged, because it has no urgent word and isn't VIP.
Review rows don't count towards accuracy, so this miss doesn't show in the
score.

## Files

```
assumptions.py       Queues, keywords, urgent words, VIP tiers, threshold
logic.py             classify, classify_all, evaluate, threshold_sweep (no Streamlit)
llm.py               Claude fallback for the review pile
app.py               Streamlit UI
sample_tickets.csv   20 labelled sample tickets
tests/test_logic.py  pytest
```
