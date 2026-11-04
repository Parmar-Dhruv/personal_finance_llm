"""
Projects detected recurring payments (Phase 5) onto concrete future dates.
Pure: no DB, no clock.

Dates are stepped from the series' real last occurrence, in calendar months
for monthly/quarterly/yearly (the 5th stays the 5th; the 31st clamps to the
month's last day) and in exact days for weekly/biweekly. The stored
`next_expected_date` is deliberately NOT used: it is last_date + 30.44 days,
which walks away from the real day-of-month within a year.

Month-end drift (known, harmless for totals): stepping a clamped date forward
keeps the clamp, so a payment last seen on 28 Feb is projected on 28 Mar, not
31 Mar. It always lands in the correct MONTH, so period totals and period-end
balances are unaffected; only the day shown inside the month can be early.

Overdue rule. If the next expected date has already passed as of the last
transaction we have, either the payment is late to post or it was skipped. We
cannot tell which. If it is overdue by no more than the cadence's own
tolerance (the same tolerance the detector accepted when it found the series)
it is assumed still pending and placed on the first forecast day, because
under-counting a bill is the unsafe direction for a "can I afford it" answer.
Further overdue, it is treated as skipped and the schedule rolls on.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.ml.recurring import CADENCES

_MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}
_DAYS = {"weekly": 7, "biweekly": 14}


def add_months(d: date, n: int) -> date:
    year, month0 = divmod(d.year * 12 + d.month - 1 + n, 12)
    month = month0 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


@dataclass(frozen=True)
class Item:
    account_id: object
    merchant: str
    type: str  # "debit" | "credit"
    cadence: str
    amount: Decimal  # the detector's recent typical amount
    amount_variable: bool
    confidence: float
    last_date: date


@dataclass(frozen=True)
class Occurrence:
    item: Item
    on: date
    assumed_pending: bool


def _step(item: Item, k: int) -> date:
    if item.cadence in _DAYS:
        return item.last_date + timedelta(days=_DAYS[item.cadence] * k)
    return add_months(item.last_date, _MONTHS[item.cadence] * k)


def project(items: list[Item], as_of: date, end: date) -> list[Occurrence]:
    """Every occurrence in (as_of, end], earliest first."""
    out: list[Occurrence] = []
    for item in items:
        tolerance_days = CADENCES[item.cadence][1]
        for k in range(1, 400):  # 400 > weekly steps in any plausible horizon; guards a bad cadence
            d = _step(item, k)
            if d > end:
                break
            if d > as_of:
                out.append(Occurrence(item, d, False))
            elif (as_of - d).days <= tolerance_days:
                out.append(Occurrence(item, as_of + timedelta(days=1), True))
            # else: further overdue than the cadence tolerates -> skipped, not projected
    out.sort(key=lambda o: (o.on, o.item.merchant, o.item.type))
    return out
