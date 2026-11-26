"""Create the schema and fill it with synthetic tickets.

    python scripts/seed.py            # schema + 200 tickets (skips if tickets exist)
    python scripts/seed.py --reset    # wipe tickets, labels and results first
    python scripts/seed.py -n 500     # a different number of tickets

Every ticket also gets a ground-truth label in ticket_labels, so later
steps can measure how accurate the rules and the LLM are. Roughly 15% of
tickets are deliberately ambiguous: they mix two issues or are too vague
for keyword rules, which is where the LLM should earn its keep.
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402

from triage.config import REPO_ROOT, Settings  # noqa: E402

TEAMS = {
    "billing": "Billing",
    "bug": "Engineering",
    "outage": "SRE",
    "access": "Support",
    "feature_request": "Product",
    "how_to": "Support",
}

COMPANIES = [
    "Acme Logistics", "Brightwater Health", "Cobalt Retail", "Delta Freight",
    "Evergreen Schools", "Fjord Analytics", "Granite Insurance", "Harbor Foods",
    "Ironclad Security", "Juniper Travel", "Kestrel Media", "Lumen Energy",
    "Meridian Bank", "Northwind Traders", "Orbit Telecom", "Pinnacle Legal",
]
ENTERPRISE = {"Meridian Bank", "Granite Insurance", "Orbit Telecom", "Brightwater Health"}
CHANNELS = ["email", "web", "chat", "phone"]
FEATURES = ["the dashboard", "CSV export", "the reports page", "SSO login", "the mobile app",
            "the API", "invoice download", "user management", "search", "notifications"]
NAMES = ["Priya", "Tom", "Aisha", "Marco", "Chen", "Sofia", "James", "Fatima", "Lukas", "Grace"]

# (subject, body, priority) templates per category. {f} feature, {n} name, {x} number.
TEMPLATES = {
    "billing": [
        ("Charged twice this month", "Hi, our card was charged twice for the {m} invoice. Can you refund the duplicate payment? Invoice #{x}.", "P2"),
        ("Invoice amount is wrong", "The invoice #{x} shows {s} seats but we only have {k}. Please correct the billing.", "P3"),
        ("Need a copy of our invoice", "Could you send a PDF of invoice #{x} for our accounts team? Thanks, {n}", "P4"),
        ("Refund request", "We cancelled our subscription last week but were still billed. Requesting a refund please.", "P2"),
        ("Update payment method", "Our company card expires next month. How do we update the payment method before the next charge?", "P3"),
        ("VAT missing from invoice", "Our finance team needs the VAT number shown on invoice #{x}. Can billing reissue it?", "P3"),
    ],
    "bug": [
        ("Error when exporting", "When I click export on {f} I get 'Error 500: unexpected error'. Started this morning. Steps: open {f}, click export.", "P2"),
        ("{F} shows wrong numbers", "The totals on {f} don't match the underlying data. Looks like a bug in the calculation since the last release.", "P2"),
        ("Button not working", "The save button on {f} does nothing when clicked. Tried Chrome and Firefox. Console shows a TypeError.", "P3"),
        ("App crashes on upload", "The app crashes every time I upload a file bigger than {x}KB. Stack trace attached.", "P2"),
        ("Typo on settings page", "Minor thing: the settings page says 'Notifcations'. Not urgent.", "P4"),
        ("Dates displayed incorrectly", "Dates on {f} show in US format even though our locale is UK. Bug or setting?", "P3"),
    ],
    "outage": [
        ("URGENT: site is down", "Nothing loads, we get a 503 on every page. All of our users are affected. Please help ASAP.", "P1"),
        ("Production outage - API not responding", "Our integration is failing, the API times out on every request since {h}:00. This is blocking our business.", "P1"),
        ("Cannot access anything", "The whole platform is down for our team, login page won't even load. Everyone is blocked.", "P1"),
        ("Service unavailable", "We're seeing 'service unavailable' across the product. Is there an outage? Our operations are stopped.", "P1"),
    ],
    "access": [
        ("Can't log in", "I reset my password but still can't log in. It says invalid credentials. Username {n}.", "P3"),
        ("Locked out of account", "My account got locked after too many attempts. Can you unlock it? I need it for a meeting at {h}:00.", "P2"),
        ("Add new user", "Please give our new starter {n} access to the workspace with admin permissions.", "P3"),
        ("2FA code not arriving", "I'm not receiving the two-factor authentication code by SMS, so I can't sign in.", "P2"),
        ("Remove access for leaver", "{n} has left the company, please remove their account and revoke access today.", "P2"),
        ("Permission denied on {f}", "I get 'permission denied' when opening {f}. My colleague can open it fine. Can you check my role?", "P3"),
    ],
    "feature_request": [
        ("Feature request: dark mode", "It would be great if the app had a dark mode. Several of our team have asked for it.", "P4"),
        ("Suggestion for {f}", "Would be nice if {f} could filter by date range. Any plans to add this?", "P4"),
        ("Can you add Slack integration?", "We'd love to get notifications in Slack. Is that on the roadmap?", "P4"),
        ("Request: bulk edit", "Please add the ability to bulk edit records on {f}. Doing it one by one takes hours.", "P4"),
        ("Idea: scheduled reports", "Feature idea: let us schedule {f} to be emailed weekly to managers.", "P4"),
    ],
    "how_to": [
        ("How do I export data?", "How do I export my data from {f} to Excel? I couldn't find it in the docs.", "P4"),
        ("Question about {f}", "Quick question: how do I change the default view on {f}?", "P4"),
        ("Where is the API documentation?", "Where can I find documentation for the API? We want to build an integration.", "P4"),
        ("How to set up SSO", "What are the steps to configure SSO with Okta for our organisation?", "P3"),
        ("Training for new team", "Do you have any guides or training material for new users? We have {k} people starting.", "P4"),
    ],
}

# Ambiguous tickets: (subject, body, true category, priority). These mix two
# issues, use vague or indirect language, or avoid the obvious keywords.
AMBIGUOUS = [
    ("Problem", "It doesn't work. Please fix.", "bug", "P3"),
    ("Not happy", "Honestly the last two weeks have been a nightmare with your product. Sort it out.", "bug", "P3"),
    ("Charged but can't log in", "We paid yesterday but now none of us can log in. Is our account suspended for non-payment?", "access", "P2"),
    ("Export broken and invoice question", "Export to CSV is failing, also can you resend last month's invoice?", "bug", "P2"),
    ("Is something going on?", "Things are really slow for us today, pages take a minute to load. Just us?", "outage", "P2"),
    ("Following up", "Following up on my previous email, still waiting for an answer.", "how_to", "P3"),
    ("Numbers look off", "The figures on our monthly statement don't look right compared to the dashboard.", "billing", "P3"),
    ("Can we get this sorted before Friday", "Our auditors need everything by Friday and we can't get at the data we need.", "access", "P2"),
    ("Downgrade", "We'd like fewer seats from next month. What happens to the users we remove?", "billing", "P3"),
    ("Missing data", "Half of last week's records have disappeared from the reports.", "bug", "P1"),
    ("Integration stopped", "Our nightly sync stopped working, nothing has come through since Tuesday.", "bug", "P2"),
    ("Thoughts on the new layout", "The new layout makes it really hard to find anything. Can we have the old one back?", "feature_request", "P4"),
    ("Security concern", "One of our users can see records from another department. That shouldn't be possible.", "access", "P1"),
    ("Contract renewal", "Our renewal is coming up, who should we talk to about the terms?", "billing", "P4"),
    ("Help!!", "Nothing is saving and I have a deadline in an hour.", "bug", "P2"),
    ("Le tableau de bord ne charge pas", "Bonjour, le tableau de bord ne se charge plus depuis ce matin. Merci de votre aide.", "bug", "P2"),
    ("Question about limits", "We keep hitting a limit on the API, do we need to pay for a higher tier or is it a bug?", "billing", "P3"),
    ("Weird emails", "Our users are getting password reset emails they didn't ask for.", "access", "P2"),
]

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November"]


def _fill(subject: str, body: str, rng: random.Random) -> tuple[str, str]:
    """Fill both templates from one set of values, so subject and body agree."""
    f = rng.choice(FEATURES)
    values = dict(
        f=f, F=f[0].upper() + f[1:], n=rng.choice(NAMES), x=rng.randint(1000, 9999),
        h=rng.randint(8, 17), m=rng.choice(MONTHS), s=rng.randint(20, 60), k=rng.randint(3, 19),
    )
    return subject.format(**values), body.format(**values)


def generate(n: int, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    now = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
    weights = {"billing": 18, "bug": 24, "outage": 6, "access": 20, "feature_request": 12, "how_to": 20}
    tickets = []
    n_ambiguous = round(n * 0.15)
    ambiguous_pool = AMBIGUOUS * (n_ambiguous // len(AMBIGUOUS) + 1)
    rng.shuffle(ambiguous_pool)
    for i in range(n):
        customer = rng.choice(COMPANIES)
        if i < n_ambiguous:
            subject, body, category, priority = ambiguous_pool[i]
            ambiguous = True
        else:
            category = rng.choices(list(weights), weights=list(weights.values()))[0]
            subject, body, priority = rng.choice(TEMPLATES[category])
            subject, body = _fill(subject, body, rng)
            ambiguous = False
        # Enterprise customers get bumped one level, except P1 and feature requests.
        if customer in ENTERPRISE and priority in ("P2", "P3") and category != "feature_request":
            priority = f"P{int(priority[1]) - 1}"
        tickets.append({
            "subject": subject,
            "body": body,
            "customer": customer,
            "channel": rng.choice(CHANNELS),
            "created_at": now - timedelta(minutes=rng.randint(0, 60 * 24 * 14)),
            "category": category,
            "priority": priority,
            "team": TEAMS[category],
            "is_ambiguous": ambiguous,
        })
    rng.shuffle(tickets)
    tickets.sort(key=lambda t: t["created_at"])
    return tickets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-n", type=int, default=200, help="number of tickets (default 200)")
    parser.add_argument("--reset", action="store_true", help="delete existing tickets, labels and results first")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    settings = Settings.load()
    engine = create_engine(settings.database_url)
    schema = (REPO_ROOT / "db" / "schema.sql").read_text()

    with engine.begin() as conn:
        conn.exec_driver_sql(schema)
        if args.reset:
            conn.execute(text("TRUNCATE triage_results, ticket_labels, tickets RESTART IDENTITY CASCADE"))
        existing = conn.execute(text("SELECT count(*) FROM tickets")).scalar_one()
        if existing:
            print(f"tickets already has {existing} rows; use --reset to replace them.")
            return
        for t in generate(args.n, args.seed):
            ticket_id = conn.execute(
                text("INSERT INTO tickets (subject, body, customer, channel, created_at) "
                     "VALUES (:subject, :body, :customer, :channel, :created_at) RETURNING id"),
                t,
            ).scalar_one()
            conn.execute(
                text("INSERT INTO ticket_labels (ticket_id, category, priority, team, is_ambiguous) "
                     "VALUES (:id, :category, :priority, :team, :is_ambiguous)"),
                {**t, "id": ticket_id},
            )
    print(f"Seeded {args.n} tickets.")


if __name__ == "__main__":
    main()
