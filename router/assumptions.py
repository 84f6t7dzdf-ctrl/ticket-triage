"""Tunable assumptions for the ticket router.

Every value here is an estimate, chosen to be a reasonable starting point
rather than measured from real data. Change them and re-run the app to see
the effect on accuracy.
"""

# Estimate: the five queues a typical support team routes into.
QUEUES = ["Billing", "Technical", "Account", "Sales", "General"]

# Estimate: words that usually signal each queue. Matched as whole words or
# phrases, case-insensitive. A hit in the subject counts double.
KEYWORDS = {
    "Billing": ["invoice", "refund", "charged", "payment", "billing", "receipt", "vat"],
    "Technical": ["error", "bug", "crash", "broken", "outage", "down", "slow", "not loading"],
    "Account": ["login", "log in", "password", "locked", "2fa", "access", "permission", "username"],
    "Sales": ["pricing", "quote", "upgrade", "demo", "seats", "contract", "plan"],
    "General": ["how do i", "question", "feedback", "feature", "documentation", "training"],
}

# Estimate: words that mean a ticket needs attention now.
URGENT_WORDS = ["urgent", "asap", "outage", "down", "immediately", "security", "breach", "locked out"]

# Estimate: customer tiers whose tickets are always treated as urgent.
VIP_TIERS = ["Enterprise"]

# Estimate: below this share of keyword hits, the top queue isn't trusted
# and the ticket goes to the "Review" pile for a person to route.
CONFIDENCE_THRESHOLD = 0.6
