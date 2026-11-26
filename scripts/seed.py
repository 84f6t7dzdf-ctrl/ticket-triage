"""Create the schema and fill it with synthetic tickets.

    python scripts/seed.py            # schema + 200 tickets (skips if tickets exist)
    python scripts/seed.py --reset    # drop and recreate the tables first
    python scripts/seed.py -n 500     # a different number of tickets

Each ticket has a subject, body, customer, customer tier and channel. Every
ticket also gets a ground-truth label in ticket_labels (queue, ticket type,
priority, VIP flag), so later steps can measure how accurate the rules and
the LLM are. Roughly 15% of tickets are deliberately ambiguous: they mix two
issues or are too vague for keyword rules, which is where the LLM should
earn its keep.
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402

from triage.config import REPO_ROOT, Settings, load_vip_customers  # noqa: E402

QUEUES = ["Billing", "Technical", "Account", "Sales", "General"]
TICKET_TYPES = ["outage", "cant_login", "security", "payment_failed", "standard"]
TIERS = ["enterprise", "business", "starter"]

# Each customer has a fixed tier. VIPs come from config/vip_customers.yaml
# and are all enterprise accounts.
CUSTOMERS = {
    "Meridian Bank": "enterprise", "Orbit Telecom": "enterprise", "Brightwater Health": "enterprise",
    "Granite Insurance": "enterprise", "Ironclad Security": "enterprise",
    "Acme Logistics": "business", "Cobalt Retail": "business", "Delta Freight": "business",
    "Fjord Analytics": "business", "Kestrel Media": "business", "Lumen Energy": "business",
    "Evergreen Schools": "starter", "Harbor Foods": "starter", "Juniper Travel": "starter",
    "Northwind Traders": "starter", "Pinnacle Legal": "starter", "Quill Studio": "starter",
}
CHANNELS = ["email", "web", "chat", "phone"]
FEATURES = ["the dashboard", "CSV export", "the reports page", "the mobile app",
            "the API", "invoice download", "user management", "search", "notifications"]
NAMES = ["Priya", "Tom", "Aisha", "Marco", "Chen", "Sofia", "James", "Fatima", "Lukas", "Grace"]

# (subject, body, queue, ticket_type, base priority).
# {f} feature, {F} capitalised feature, {n} name, {x} number, {h} hour,
# {m} month, {s}/{k} seat counts.
TEMPLATES = [
    # Billing, payment failed
    ("Payment failed", "We got an email saying our payment failed for the {m} renewal. The card is valid. Can you retry it?", "Billing", "payment_failed", "P2"),
    ("Card declined on renewal", "Our subscription renewal was declined. Card ending {x}. Please advise before we lose access.", "Billing", "payment_failed", "P2"),
    ("Direct debit bounced", "Our bank says your direct debit for invoice #{x} bounced. What do we need to do?", "Billing", "payment_failed", "P2"),
    ("Account suspended for non-payment", "We've been suspended because a payment failed, but we paid invoice #{x} last week. Please restore access.", "Billing", "payment_failed", "P2"),
    # Billing, standard
    ("Charged twice this month", "Hi, our card was charged twice for the {m} invoice. Can you refund the duplicate? Invoice #{x}.", "Billing", "standard", "P3"),
    ("Invoice amount is wrong", "Invoice #{x} shows {s} seats but we only have {k}. Please correct it.", "Billing", "standard", "P3"),
    ("Need a copy of our invoice", "Could you send a PDF of invoice #{x} for our accounts team? Thanks, {n}", "Billing", "standard", "P4"),
    ("Refund request", "We cancelled last week but were still billed. Requesting a refund please.", "Billing", "standard", "P3"),
    ("VAT missing from invoice", "Our finance team needs our VAT number on invoice #{x}. Can you reissue it?", "Billing", "standard", "P4"),
    ("Update card details", "Our company card expires next month. How do we update the payment method?", "Billing", "standard", "P4"),
    # Technical, outage
    ("URGENT: site is down", "Nothing loads, we get a 503 on every page. All of our users are affected. Please help ASAP.", "Technical", "outage", "P1"),
    ("Production outage - API not responding", "Our integration is failing, the API times out on every request since {h}:00. This is blocking our business.", "Technical", "outage", "P1"),
    ("Whole platform down", "The platform is down for our whole team, pages won't load at all. Everyone is blocked.", "Technical", "outage", "P1"),
    ("Service unavailable", "We're seeing 'service unavailable' across the product. Is there an outage? Our operations have stopped.", "Technical", "outage", "P1"),
    # Technical, standard
    ("Error when exporting", "When I click export on {f} I get 'Error 500'. Started this morning. Steps: open {f}, click export.", "Technical", "standard", "P2"),
    ("{F} shows wrong numbers", "The totals on {f} don't match the underlying data. Looks like a bug since the last release.", "Technical", "standard", "P2"),
    ("Save button not working", "The save button on {f} does nothing. Tried Chrome and Firefox. Console shows a TypeError.", "Technical", "standard", "P3"),
    ("App crashes on upload", "The app crashes every time I upload a file bigger than {x}KB.", "Technical", "standard", "P2"),
    ("Typo on settings page", "Minor thing: the settings page says 'Notifcations'. Not urgent.", "Technical", "standard", "P4"),
    ("Slow page loads", "{F} takes 20 seconds to load for us since yesterday. Other pages are fine.", "Technical", "standard", "P3"),
    # Account, can't log in
    ("Can't log in", "I reset my password but still can't log in. It says invalid credentials. Username {n}.", "Account", "cant_login", "P2"),
    ("Locked out of account", "My account got locked after too many attempts. Can you unlock it? I need it for a meeting at {h}:00.", "Account", "cant_login", "P2"),
    ("2FA code not arriving", "I'm not receiving the two-factor code by SMS, so I can't sign in.", "Account", "cant_login", "P2"),
    ("SSO login failing", "Our team can't sign in through SSO this morning, it loops back to the login page.", "Account", "cant_login", "P2"),
    ("Password reset link expired", "Every password reset link I get says it has expired, so I'm stuck at the login screen.", "Account", "cant_login", "P3"),
    # Account, security
    ("Suspicious login on our account", "We got an alert about a login from a country we don't operate in. Was our account compromised?", "Account", "security", "P1"),
    ("Possible data breach", "One of our users can see records belonging to another company. This looks like a serious security issue.", "Account", "security", "P1"),
    ("API key leaked", "A developer accidentally pushed our API key to a public repo. Please revoke it and help us rotate.", "Account", "security", "P1"),
    ("Phishing email using your brand", "Our staff received a phishing email pretending to be from you asking for passwords.", "Account", "security", "P2"),
    ("Unknown admin user added", "There's an admin user called '{n}-temp' in our workspace that nobody here created.", "Account", "security", "P1"),
    # Account, standard
    ("Add new user", "Please give our new starter {n} access to the workspace with admin permissions.", "Account", "standard", "P3"),
    ("Remove access for leaver", "{n} has left the company, please remove their account today.", "Account", "standard", "P3"),
    ("Change account email", "How do I change the email address on my account? I've changed jobs internally.", "Account", "standard", "P4"),
    ("Permission denied on {f}", "I get 'permission denied' on {f}. My colleague can open it. Can you check my role?", "Account", "standard", "P3"),
    # Sales
    ("Upgrade to a higher plan", "We'd like to move from our current plan to the next tier up. Who can help with pricing?", "Sales", "standard", "P3"),
    ("Pricing for more seats", "We're growing and need about {s} more seats. Can you send a quote?", "Sales", "standard", "P3"),
    ("Demo for another department", "Our {m} budget is approved and another department wants a demo. Can someone get in touch?", "Sales", "standard", "P3"),
    ("Renewal quote", "Our contract renews in {m}. Can we get a renewal quote and discuss multi-year terms?", "Sales", "standard", "P3"),
    ("Enterprise plan question", "Does the enterprise plan include SSO and an SLA? We're comparing vendors this month.", "Sales", "standard", "P3"),
    # General
    ("How do I export data?", "How do I export my data from {f} to Excel? I couldn't find it in the docs.", "General", "standard", "P4"),
    ("Question about {f}", "Quick question: how do I change the default view on {f}?", "General", "standard", "P4"),
    ("Where is the API documentation?", "Where can I find the API docs? We want to build an integration.", "General", "standard", "P4"),
    ("Feature request: dark mode", "It would be great if the app had a dark mode. Several of our team have asked for it.", "General", "standard", "P4"),
    ("Suggestion for {f}", "Would be nice if {f} could filter by date range. Any plans to add this?", "General", "standard", "P4"),
    ("Training for new team", "Do you have guides or training for new users? We have {k} people starting.", "General", "standard", "P4"),
]

# Ambiguous tickets: (subject, body, queue, ticket_type, priority). They mix
# two issues, use vague or indirect wording, or avoid the obvious keywords.
AMBIGUOUS = [
    ("Problem", "It doesn't work. Please fix.", "Technical", "standard", "P3"),
    ("Not happy", "Honestly the last two weeks have been a nightmare with your product. Sort it out.", "General", "standard", "P3"),
    ("Paid but can't get in", "We paid yesterday but now none of us can sign in. Is the account suspended?", "Account", "cant_login", "P2"),
    ("Export broken and invoice question", "Export to CSV is failing, also can you resend last month's invoice?", "Technical", "standard", "P2"),
    ("Is something going on?", "Things are really slow for everyone here today, pages take a minute to load. Just us?", "Technical", "outage", "P2"),
    ("Following up", "Following up on my previous email, still waiting for an answer.", "General", "standard", "P3"),
    ("Numbers look off", "The figures on our monthly statement don't match what we agreed.", "Billing", "standard", "P3"),
    ("Need this before Friday", "Our auditors need everything by Friday and we can't get at the data we need.", "Account", "cant_login", "P2"),
    ("Fewer seats next month", "We'd like fewer seats from next month. What happens to the users we remove?", "Sales", "standard", "P3"),
    ("Missing data", "Half of last week's records have disappeared from the reports.", "Technical", "standard", "P1"),
    ("Odd activity", "Someone changed our notification settings overnight and none of us did it.", "Account", "security", "P1"),
    ("Thoughts on the new layout", "The new layout makes it really hard to find anything. Can we have the old one back?", "General", "standard", "P4"),
    ("Renewal didn't go through", "Got a message that the renewal didn't go through. Do we need to talk to someone about the contract?", "Billing", "payment_failed", "P2"),
    ("Help!!", "Nothing is saving and I have a deadline in an hour.", "Technical", "standard", "P2"),
    ("Le tableau de bord ne charge pas", "Bonjour, le tableau de bord ne se charge plus depuis ce matin pour toute l'equipe.", "Technical", "outage", "P1"),
    ("API limits", "We keep hitting a limit on the API. Do we need a bigger plan or is it a bug?", "Sales", "standard", "P3"),
    ("Weird emails", "Our users are getting password reset emails they didn't ask for.", "Account", "security", "P2"),
    ("Who do I talk to?", "We want to roll this out to the whole company. Who's the right person?", "Sales", "standard", "P3"),
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


def _bump(priority: str) -> str:
    """Raise a priority one level (P3 -> P2), never above P1."""
    return f"P{max(1, int(priority[1]) - 1)}"


def generate(n: int, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    vips = load_vip_customers()
    now = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
    n_ambiguous = round(n * 0.15)
    ambiguous_pool = AMBIGUOUS * (n_ambiguous // len(AMBIGUOUS) + 1)
    rng.shuffle(ambiguous_pool)
    # Weight the templates so the special ticket types are a minority, as in
    # a real queue: standard tickets about 70%, each special type about 7%.
    weights = [1.0 if t[3] == "standard" else 0.6 for t in TEMPLATES]
    tickets = []
    for i in range(n):
        customer = rng.choice(list(CUSTOMERS))
        tier = CUSTOMERS[customer]
        if i < n_ambiguous:
            subject, body, queue, ticket_type, priority = ambiguous_pool[i]
        else:
            subject, body, queue, ticket_type, priority = rng.choices(TEMPLATES, weights)[0]
            subject, body = _fill(subject, body, rng)
        is_vip = customer.lower() in vips
        # Escalation: VIPs go up one level; other enterprise accounts go up one
        # level unless the ticket is low-stakes (P4).
        if is_vip or (tier == "enterprise" and priority != "P4"):
            priority = _bump(priority)
        tickets.append({
            "subject": subject,
            "body": body,
            "customer": customer,
            "customer_tier": tier,
            "channel": rng.choice(CHANNELS),
            "created_at": now - timedelta(minutes=rng.randint(0, 60 * 24 * 14)),
            "queue": queue,
            "ticket_type": ticket_type,
            "priority": priority,
            "is_vip": is_vip,
            "is_ambiguous": i < n_ambiguous,
        })
    tickets.sort(key=lambda t: t["created_at"])
    return tickets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-n", type=int, default=200, help="number of tickets (default 200)")
    parser.add_argument("--reset", action="store_true", help="drop and recreate tickets, labels and results first")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    settings = Settings.load()
    engine = create_engine(settings.database_url)
    schema = (REPO_ROOT / "db" / "schema.sql").read_text()

    with engine.begin() as conn:
        if args.reset:
            conn.exec_driver_sql("DROP TABLE IF EXISTS triage_results, ticket_labels, tickets CASCADE")
        conn.exec_driver_sql(schema)
        existing = conn.execute(text("SELECT count(*) FROM tickets")).scalar_one()
        if existing:
            print(f"tickets already has {existing} rows; use --reset to replace them.")
            return
        for t in generate(args.n, args.seed):
            ticket_id = conn.execute(
                text("INSERT INTO tickets (subject, body, customer, customer_tier, channel, created_at) "
                     "VALUES (:subject, :body, :customer, :customer_tier, :channel, :created_at) RETURNING id"),
                t,
            ).scalar_one()
            conn.execute(
                text("INSERT INTO ticket_labels (ticket_id, queue, ticket_type, priority, is_vip, is_ambiguous) "
                     "VALUES (:id, :queue, :ticket_type, :priority, :is_vip, :is_ambiguous)"),
                {**t, "id": ticket_id},
            )
    print(f"Seeded {args.n} tickets.")


if __name__ == "__main__":
    main()
