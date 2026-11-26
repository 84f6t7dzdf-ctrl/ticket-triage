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
logic.py             classify, classify_all, evaluate (no Streamlit)
app.py               Streamlit UI
sample_tickets.csv   20 labelled sample tickets
tests/test_logic.py  pytest
```
