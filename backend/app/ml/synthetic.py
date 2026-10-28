"""
Synthetic labeled data. There is NO real labeled bank data in this project
(spec §19: synthetic/anonymized only), so every accuracy number the ML layer
reports comes from here. Read the numbers with that in mind:

* Merchants are split train/val/test BY MERCHANT, so the test set measures
  generalization to merchants the model never saw -- not memorization.
* Even so, the generator and the model share one author. Narration styles,
  noise and the merchant universe are my guesses at Indian bank statements,
  not samples of them. Real-world accuracy will be lower. The numbers are
  useful for comparing methods against each other, not as a promise.

Deterministic: every function takes a seed and uses its own RNG.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from app.ml.taxonomy import LABELS

# --------------------------------------------------------------------------
# Merchant universe. Deliberately includes hard cases: Amazon vs Amazon Prime
# vs AWS, Uber vs Uber Eats, Flipkart (shop) vs Flipkart Internet (employer),
# IRCTC (travel, though it looks like transport).
# --------------------------------------------------------------------------
MERCHANTS: dict[str, list[str]] = {
    "Food": [
        "Swiggy", "Zomato", "Dominos Pizza", "McDonalds", "Starbucks", "Cafe Coffee Day",
        "BigBasket", "Blinkit", "Zepto", "Haldirams", "Subway", "KFC", "Burger King",
        "Barbeque Nation", "Chai Point", "Sagar Ratna", "Faasos", "Pizza Hut", "Theobroma",
        "Reliance Fresh", "DMart", "Natures Basket", "Wow Momo", "Behrouz Biryani",
        "Green Leaf Restaurant", "Sri Balaji Tiffins", "Mehta Sweets", "Uber Eats",
        "Annapurna Bakery", "Hotel Sai Palace Dining", "Madras Cafe", "Punjabi Dhaba",
    ],
    "Transportation": [
        "Uber", "Ola Cabs", "Rapido", "Indian Oil Fuel", "HP Petrol Pump", "Bharat Petroleum",
        "Shell Fuel Station", "Delhi Metro DMRC", "BMTC Bus Pass", "FASTag Recharge", "Park Plus",
        "Namma Yatri", "Mumbai Metro One", "Shree Auto Garage", "Blu Smart", "Zoomcar",
        "Yulu Bikes", "Toll Plaza NHAI", "City Parking Services", "Lalbagh Cab Services",
        "Reliance Petrol Bunk", "Kolkata Metro", "Apex Car Service Centre", "Cars24 Servicing",
    ],
    "Shopping": [
        "Amazon", "Flipkart", "Myntra", "Ajio", "Nykaa", "Croma", "Reliance Digital", "Decathlon",
        "IKEA", "Lifestyle Stores", "Pantaloons", "Westside", "Shoppers Stop", "H&M", "Zara",
        "Meesho", "Tata Cliq", "Lenskart", "Uniqlo", "Max Fashion", "Big Bazaar Store",
        "Vijay Sales", "Fabindia", "Bata Showroom", "Sports Hub Retail", "Chroma Electronics",
        "Pepperfry Furniture", "Urban Ladder",
    ],
    "Utilities": [
        "Airtel Postpaid", "Jio Recharge", "Vodafone Idea", "BSNL Broadband", "Tata Power",
        "BESCOM Electricity", "Adani Electricity", "MSEB Bill", "Indane Gas", "Mahanagar Gas",
        "ACT Fibernet", "Hathway Broadband", "Water Board Charges", "Tata Play DTH", "Sun Direct",
        "BSES Rajdhani", "Torrent Power", "Vi Prepaid", "Airtel Xstream Fiber", "Bharat Gas Cylinder",
        "Municipal Water Supply", "Piped Gas Charges",
    ],
    "Entertainment": [
        "Netflix", "Spotify", "Amazon Prime", "Disney Hotstar", "BookMyShow", "PVR Cinemas",
        "INOX Movies", "YouTube Premium", "Sony LIV", "Zee5", "Steam Games", "PlayStation Store",
        "Gaana", "Apple Services", "Xbox Live", "Wynk Music", "Cinepolis", "Smaaash Gaming",
        "Timezone Arcade", "Audible", "Jiosaavn Pro", "Lotus Bowling Alley", "Escape Room Mumbai",
        "Comedy Club Live",
    ],
    "Healthcare": [
        "Apollo Pharmacy", "Practo", "MedPlus", "1mg", "Pharmeasy", "Fortis Hospital",
        "Max Healthcare", "Manipal Hospital", "Dr Lal PathLabs", "Thyrocare", "Netmeds",
        "Star Health Premium", "Dental Clinic Smile", "Apollo Diagnostics", "Sankara Eye Hospital",
        "Medlife", "Wellness Forever", "Aster Clinic", "City Diagnostics Lab", "Ayush Ayurveda Clinic",
        "HDFC Ergo Health", "Cloudnine Hospital",
    ],
    "Travel": [
        "MakeMyTrip", "Goibibo", "IRCTC", "IndiGo Airlines", "Air India", "Vistara", "SpiceJet",
        "Booking.com", "Airbnb", "OYO Rooms", "Cleartrip", "Yatra", "Taj Hotels", "Marriott",
        "RedBus", "Agoda", "Expedia", "Lemon Tree Hotels", "Treebo", "Ibis Hotel", "Thomas Cook",
        "Akasa Air", "Holiday Inn", "Zostel Hostel", "EaseMyTrip",
    ],
    "Rent": [
        "Rent Payment Mr Sharma", "Rent Mrs Iyer", "Monthly Rent Flat 402", "Rent to Landlord",
        "Rent Mr Reddy", "PG Rent Payment", "NoBroker Rent Pay", "Housing Rent Mr Gupta",
        "Rental Payment Villa", "Flat Rent Mrs Nair", "House Rent Mr Khan", "Rent Mr Banerjee",
        "Rent Payment Ms Fernandes", "Landlord Rent Transfer", "Apartment Rent Mr Joshi",
    ],
    "Salary": [
        "Infosys Ltd", "TCS Payroll", "Wipro Limited", "Accenture Solutions", "Cognizant Tech",
        "HCL Technologies", "Tech Mahindra", "Capgemini India", "Zoho Corp", "Freshworks Inc",
        "Razorpay Software", "Flipkart Internet", "Amazon Development Centre", "Swiggy Payroll",
        "Deloitte Consulting", "Paytm Payments Employer", "Mindtree Ltd", "Persistent Systems",
    ],
    "Business expenses": [
        "AWS", "Google Workspace", "GitHub", "Slack Technologies", "Zoom Video", "Notion Labs",
        "Atlassian", "Canva", "GoDaddy", "Digital Ocean", "Figma", "Microsoft 365",
        "Adobe Creative Cloud", "WeWork", "Regus Office", "Staples Office Supplies", "Vistaprint",
        "Zoho Books", "QuickBooks", "Mailchimp", "Cloudflare", "Shiprocket", "Stripe Fees",
        "Office Depot", "Cowrie Coworking", "Amazon Web Services", "Jira Cloud",
    ],
}

# (mu, sigma) of ln(amount in INR). Rough orders of magnitude only.
_AMOUNT_LOGNORM = {
    "Food": (6.0, 0.8), "Transportation": (5.6, 1.0), "Shopping": (7.2, 1.0),
    "Utilities": (6.9, 0.7), "Entertainment": (5.9, 0.9), "Healthcare": (6.9, 1.1),
    "Travel": (8.7, 0.9), "Rent": (9.9, 0.5), "Salary": (11.0, 0.6),
    "Business expenses": (7.6, 1.1),
}
_PRIOR = {  # share of transactions; imbalanced on purpose
    "Food": 24, "Transportation": 13, "Shopping": 15, "Utilities": 9, "Entertainment": 8,
    "Healthcare": 6, "Travel": 5, "Rent": 3, "Salary": 3, "Business expenses": 14,
}
_CITIES = ["MUMBAI", "BANGALORE", "DELHI", "PUNE", "CHENNAI", "HYDERABAD", "KOLKATA", "GURGAON", "NOIDA"]
_VPA_SUFFIX = ["okaxis", "oksbi", "okhdfcbank", "ybl", "paytm", "ibl", "axl"]
_IFSC = ["HDFC0001234", "ICIC0004321", "SBIN0000456", "UTIB0001122", "KKBK0002233"]
_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def split_of(merchant: str) -> str:
    """Deterministic merchant-level split: ~70% train, 15% val, 15% test."""
    h = int(hashlib.sha256(merchant.encode()).hexdigest(), 16) % 100
    return "train" if h < 70 else "val" if h < 85 else "test"


@dataclass
class LabeledTxn:
    description_raw: str
    merchant_normalized: str | None
    amount: float
    transaction_type: str  # debit | credit
    label: str
    merchant_key: str
    split: str


def _ref(rng: random.Random, n: int = 12) -> str:
    return "".join(rng.choice("0123456789") for _ in range(n))


def _corrupt(rng: random.Random, name: str) -> str:
    out = name.upper() if rng.random() < 0.7 else name
    if rng.random() < 0.25:  # banks truncate narrations
        out = out[: rng.randint(9, 16)].rstrip()
    if rng.random() < 0.08 and len(out) > 4:  # typo: swap two adjacent chars
        i = rng.randrange(1, len(out) - 2)
        out = out[:i] + out[i + 1] + out[i] + out[i + 2:]
    if rng.random() < 0.15:
        out = out.replace(" ", "")
    return out


def narration(rng: random.Random, name: str, label: str, when: date | None = None) -> str:
    """One bank-statement-style description for a merchant."""
    m = _corrupt(rng, name)
    when = when or date(2026, 1, 1)
    if label == "Salary":
        return rng.choice([
            f"NEFT-{rng.choice(_IFSC)}-{m}-SALARY {_MONTHS[when.month - 1]}",
            f"SALARY CREDIT {m}",
            f"NEFT/{_ref(rng, 10)}/{m} PAYROLL",
            f"IMPS/{_ref(rng)}/{m}/SAL {_MONTHS[when.month - 1]}",
        ])
    style = rng.randrange(7)
    if style == 0:
        return f"UPI/{_ref(rng)}/{m}/{m.replace(' ', '').lower()[:10]}@{rng.choice(_VPA_SUFFIX)}"
    if style == 1:
        return f"POS {_ref(rng, 4)}XXXXXX{_ref(rng, 4)} {m} {rng.choice(_CITIES)}"
    if style == 2:
        return m
    if style == 3:
        return f"IMPS/{_ref(rng)}/{m}"
    if style == 4:
        return f"PURCHASE {m} {rng.choice(_CITIES)}"
    if style == 5:
        return f"UPI-{m}-{_ref(rng, 9)}-{rng.choice(['PAYMENT', 'PAY', 'ORDER', 'BILL'])}"
    return f"{m} {_ref(rng, 6)}"


def sample_amount(rng: random.Random, label: str) -> float:
    mu, sigma = _AMOUNT_LOGNORM[label]
    amt = rng.lognormvariate(mu, sigma)
    if label == "Rent":
        amt = round(amt / 500) * 500  # rent is a round number
    return round(max(amt, 10.0), 2)


def generate_labeled(
    n: int,
    seed: int,
    split: str | None = None,
    label_noise: float = 0.0,
) -> list[LabeledTxn]:
    """
    n labeled transactions. `split` restricts merchants to one of
    train/val/test (merchant-level holdout); None uses all merchants
    (the optimistic, in-distribution setting).
    `label_noise` flips that fraction of labels to a random other class --
    training-set noise only; test sets are generated clean.
    """
    rng = random.Random(seed)
    pool: dict[str, list[str]] = {
        lab: [m for m in ms if split is None or split_of(m) == split] for lab, ms in MERCHANTS.items()
    }
    labels = [lab for lab in LABELS if pool[lab]]
    weights = [_PRIOR[lab] for lab in labels]
    out: list[LabeledTxn] = []
    for _ in range(n):
        lab = rng.choices(labels, weights)[0]
        name = rng.choice(pool[lab])
        is_credit = lab == "Salary" or rng.random() < 0.03  # 3%: refund to a merchant
        desc = narration(rng, name, lab, date(2026, rng.randint(1, 12), 1))
        if is_credit and lab != "Salary":
            desc = "REFUND " + desc
        # Half the rows carry a Phase-3-style canonical merchant (alias
        # matched); the rest only have the cleaned narration.
        canonical = name if rng.random() < 0.5 else None
        label = lab
        if label_noise and rng.random() < label_noise:
            label = rng.choice([x for x in LABELS if x != lab])
        out.append(
            LabeledTxn(
                description_raw=desc,
                merchant_normalized=canonical,
                amount=sample_amount(rng, lab),
                transaction_type="credit" if is_credit else "debit",
                label=label,
                merchant_key=name,
                split=split_of(name),
            )
        )
    return out


# --------------------------------------------------------------------------
# User histories for the recurring / anomaly / duplicate evals.
# --------------------------------------------------------------------------
@dataclass
class HistTxn:
    key: int  # index in the list, used as a stable id
    date: datetime
    merchant: str
    description: str
    amount: float
    type: str
    doc: str
    account: str = "acct"
    currency: str = "INR"
    # ground truth
    recurring_stream: str | None = None
    is_anomaly: bool = False
    anomaly_severity: str | None = None  # moderate | severe
    dup_of: int | None = None  # key of the original this duplicates


@dataclass
class History:
    txns: list[HistTxn] = field(default_factory=list)
    streams: dict[str, dict] = field(default_factory=dict)  # name -> {cadence, merchant}


def _dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def generate_history(seed: int, months: int = 12, start: date = date(2025, 11, 1)) -> History:
    """
    One synthetic user over `months` months with known ground truth:
    fixed-price subscriptions, rent, salary, drifting-amount utilities
    (all recurring), plus irregular discretionary spending (not recurring)
    with injected anomalies, plus statement-overlap duplicates.
    """
    rng = random.Random(seed)
    h = History()
    end = start + timedelta(days=int(months * 30.4))

    def add(d: date, merchant: str, amount: float, typ: str, doc: str, **kw) -> HistTxn:
        t = HistTxn(
            key=len(h.txns), date=_dt(d), merchant=merchant,
            description=kw.pop("description", None) or narration(rng, merchant, "Food", d),
            amount=round(amount, 2), type=typ, doc=doc, **kw,
        )
        h.txns.append(t)
        return t

    def monthly(name: str, merchant: str, day: int, amount: float, typ: str, jitter: int, drift: float):
        h.streams[name] = {"cadence": "monthly", "merchant": merchant}
        d = date(start.year, start.month, 1)
        while d < end:
            dd = d.replace(day=min(day, 28)) + timedelta(days=rng.randint(-jitter, jitter))
            if start <= dd < end:
                amt = amount * (1 + rng.uniform(-drift, drift))
                add(dd, merchant, amt, typ, f"doc-{dd:%Y-%m}", recurring_stream=name)
            d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)

    # Streams
    monthly("salary", "Infosys Ltd", 1, 85000, "credit", 1, 0.0)
    monthly("rent", "Rent Mr Sharma", 5, 22000, "debit", 2, 0.0)
    monthly("netflix", "Netflix", 12, 649, "debit", 1, 0.0)
    monthly("spotify", "Spotify", 18, 119, "debit", 1, 0.0)
    monthly("electricity", "BESCOM Electricity", 20, 1800, "debit", 3, 0.30)
    monthly("broadband", "ACT Fibernet", 8, 1179, "debit", 2, 0.0)
    # Weekly stream: a gym/tiffin subscription charged every 7 days.
    h.streams["tiffin"] = {"cadence": "weekly", "merchant": "Sri Balaji Tiffins"}
    d = start
    while d < end:
        add(d, "Sri Balaji Tiffins", 700.0, "debit", f"doc-{d:%Y-%m}", recurring_stream="tiffin")
        d += timedelta(days=7)

    # Discretionary (NOT recurring): irregular intervals, varying amounts,
    # including heavy-use merchants (Swiggy ~3x/week) that look "frequent"
    # but are not a subscription.
    habit = [("Swiggy", "Food"), ("Zomato", "Food"), ("Uber", "Transportation"),
             ("Amazon", "Shopping"), ("BigBasket", "Food"), ("Apollo Pharmacy", "Healthcare"),
             ("Decathlon", "Shopping"), ("BookMyShow", "Entertainment"), ("MakeMyTrip", "Travel")]
    n_disc = months * 38
    span = (end - start).days
    for _ in range(n_disc):
        m, lab = rng.choice(habit)
        d = start + timedelta(days=rng.randrange(span))
        add(d, m, sample_amount(rng, lab), "debit", f"doc-{d:%Y-%m}")

    # Inject anomalies into discretionary rows only (5-15x the usual amount).
    disc = [t for t in h.txns if t.recurring_stream is None]
    # Two severities, because an anomaly that is only ~2 sigma beyond a
    # merchant's normal spread is indistinguishable from a big-but-ordinary
    # purchase -- reporting recall on those as if the detector "should" get
    # them would grade the data, not the detector. 'moderate' (x4-12) and
    # 'severe' (x15-40) are reported separately.
    picks = rng.sample(disc, max(4, int(0.02 * len(disc))))
    for i, t in enumerate(picks):
        severe = i % 2 == 0
        t.amount = round(t.amount * (rng.uniform(15, 40) if severe else rng.uniform(4, 12)), 2)
        t.is_anomaly, t.anomaly_severity = True, "severe" if severe else "moderate"

    # Statement-overlap duplicates: a re-uploaded statement repeats ~8% of
    # rows into a *different* document, same date (or +-1 day for the
    # posting-date shift case), same amount and narration.
    originals = list(h.txns)
    for t in rng.sample(originals, int(0.08 * len(originals))):
        shift = rng.choice([0, 0, 0, 1, -1])
        c = HistTxn(
            key=len(h.txns), date=t.date + timedelta(days=shift), merchant=t.merchant,
            description=t.description, amount=t.amount, type=t.type,
            doc=f"reupload-{t.doc}", recurring_stream=None, is_anomaly=t.is_anomaly, anomaly_severity=t.anomaly_severity, dup_of=t.key,
        )
        h.txns.append(c)
    return h
