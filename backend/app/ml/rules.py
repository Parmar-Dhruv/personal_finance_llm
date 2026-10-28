"""
Rule-based classifier: the baseline the ML model has to beat.

Ordered (first match wins), regex over the lowercased narration + canonical
merchant. Order matters: "uber eats" must be tried before "uber", and
"amazon prime" / "amazon web services" before bare "amazon".

Written by hand from general knowledge of Indian/US merchants and generic
words (pharmacy, hospital, fuel...), NOT fitted to the evaluation merchants
-- but its author also wrote the synthetic merchant list, so expect it to
look somewhat better here than on real statements. A rule hit is a
precise-but-narrow signal: high confidence when it fires, silent otherwise.
"""

from __future__ import annotations

import re

from app.ml.taxonomy import CREDIT_ONLY

RULE_CONFIDENCE = 0.90

# (label, pattern). Credits-only labels are skipped for debits at match time.
_RULES: list[tuple[str, str]] = [
    # --- order-sensitive specifics first ---
    ("Food", r"uber\s*eats|swiggy|zomato|zepto|blinkit|bigbasket|dominos|domino's|mcdonald|kfc\b|burger king|pizza|starbucks|"
             r"cafe coffee|chai|restaurant|dhaba|bakery|biryani|tiffin|sweets|momo|caf[eé]\b|kitchen|dining|dmart|grocer|supermarket|fresh\b"),
    ("Entertainment", r"amazon\s*prime|prime video|netflix|spotify|hotstar|youtube\s*premium|bookmyshow|pvr|inox|cinema|cinepolis|"
                      r"sony\s*liv|zee5|steam|playstation|xbox|gaana|wynk|audible|saavn|arcade|bowling|gaming"),
    ("Business expenses", r"amazon\s*web\s*services|\baws\b|google\s*workspace|github|slack|zoom\b|notion|atlassian|jira|figma|canva|"
                          r"godaddy|digital\s*ocean|cloudflare|microsoft\s*365|adobe|wework|regus|cowork|stripe|quickbooks|zoho\s*books|"
                          r"mailchimp|office\s*(supplies|depot)|staples|vistaprint|shiprocket"),
    ("Healthcare", r"pharm|medplus|\b1mg\b|netmeds|medlife|hospital|clinic|diagnostic|pathlab|thyrocare|practo|dental|doctor|"
                   r"health\s*(insurance|premium)|star health|wellness forever|\blab\b"),
    ("Travel", r"makemytrip|goibibo|irctc|indigo|air\s*india|vistara|spicejet|akasa|airlines?|booking\.com|airbnb|\boyo\b|cleartrip|"
               r"yatra|taj hotels|marriott|redbus|agoda|expedia|hotels?\b|hostel|thomas cook|easemytrip|resort"),
    ("Transportation", r"uber|ola\s*cabs|\bola\b|rapido|petrol|fuel|diesel|indian\s*oil|bharat\s*petroleum|\bhp\b|shell|metro|fastag|"
                       r"toll|parking|cab\b|taxi|bus\s*pass|auto\s*garage|car\s*service"),
    ("Utilities", r"electric|\bpower\b|bescom|bses|torrent|water\s*(board|supply|charges)|\bgas\b|indane|broadband|fibernet|fiber|"
                  r"airtel|jio\b|vodafone|\bvi\b|bsnl|dth|tata\s*play|sun\s*direct|recharge|postpaid|prepaid"),
    ("Rent", r"\brent\b|rental|landlord|nobroker|\bpg\b"),
    ("Shopping", r"amazon|flipkart|myntra|ajio|nykaa|croma|reliance\s*digital|decathlon|ikea|lifestyle|pantaloons|westside|shoppers\s*stop|"
                 r"h&m|zara|meesho|tata\s*cliq|lenskart|uniqlo|max\s*fashion|bazaar|vijay\s*sales|fabindia|showroom|retail|furniture"),
    ("Salary", r"salary|payroll|\bsal\b"),
]
_COMPILED = [(lab, re.compile(pat, re.IGNORECASE)) for lab, pat in _RULES]


def classify_rules(text: str, transaction_type: str) -> tuple[str, float] | None:
    """(label, confidence) for the first matching rule, else None."""
    # Salary is the one rule that must run first for credits: an employer
    # name like "Swiggy Payroll" would otherwise hit the Food rule.
    if transaction_type == "credit":
        for lab, rx in _COMPILED:
            if lab == "Salary" and rx.search(text):
                return lab, RULE_CONFIDENCE
    for lab, rx in _COMPILED:
        if lab in CREDIT_ONLY and transaction_type != "credit":
            continue
        if rx.search(text):
            return lab, RULE_CONFIDENCE
    return None
