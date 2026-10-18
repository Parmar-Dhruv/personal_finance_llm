"""Income / expense / net cash-flow, overall and month by month."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.common import (
    ZERO,
    count_by_type,
    money,
    Scope,
    month_end,
    month_start,
    next_month,
    pct,
    scope_conditions,
    sum_by_type,
)
from app.db.models import Transaction, TransactionType


@dataclass(frozen=True)
class CurrencySummary:
    currency: str
    income: Decimal
    expense: Decimal
    net: Decimal
    income_count: int
    expense_count: int
    # net / income as a percentage. None when there's no income in the
    # window — "savings rate" is undefined there, not 0 and not -inf.
    savings_rate_pct: Decimal | None


def summary(db: Session, scope: Scope) -> list[CurrencySummary]:
    stmt = (
        select(
            Transaction.currency,
            sum_by_type(TransactionType.credit),
            sum_by_type(TransactionType.debit),
            count_by_type(TransactionType.credit),
            count_by_type(TransactionType.debit),
        )
        .where(*scope_conditions(scope))
        .group_by(Transaction.currency)
        .order_by(Transaction.currency)
    )
    out = []
    for currency, income, expense, income_count, expense_count in db.execute(stmt).all():
        income, expense = money(income), money(expense)
        net = income - expense
        out.append(
            CurrencySummary(
                currency=currency,
                income=income,
                expense=expense,
                net=net,
                income_count=income_count,
                expense_count=expense_count,
                savings_rate_pct=pct(net, income),
            )
        )
    return out


@dataclass(frozen=True)
class MonthPoint:
    month: date  # first day of the month
    income: Decimal
    expense: Decimal
    net: Decimal
    transaction_count: int
    # True when the requested date range clips this month, so its totals
    # cover only part of it and a month-over-month comparison against a
    # full month is apples-to-oranges.
    partial: bool
    # Change vs the immediately preceding calendar month in the series
    # (None for the first point). *_change_pct is None when the previous
    # month's value is 0 — a percentage change from zero is undefined.
    income_change: Decimal | None
    income_change_pct: Decimal | None
    expense_change: Decimal | None
    expense_change_pct: Decimal | None
    net_change: Decimal | None


@dataclass(frozen=True)
class CurrencyMonthly:
    currency: str
    months: list[MonthPoint] = field(default_factory=list)


def monthly(db: Session, scope: Scope) -> list[CurrencyMonthly]:
    # Rows are stored as midnight-UTC calendar dates, so UTC is the right
    # zone to bucket in; converting first keeps date_trunc from depending
    # on the DB session's TimeZone setting.
    bucket = func.date_trunc("month", func.timezone("UTC", Transaction.transaction_date)).label("bucket")
    stmt = (
        select(
            Transaction.currency,
            bucket,
            sum_by_type(TransactionType.credit),
            sum_by_type(TransactionType.debit),
            func.count(),
        )
        .where(*scope_conditions(scope))
        .group_by(Transaction.currency, bucket)
        .order_by(Transaction.currency, bucket)
    )

    per_currency: dict[str, dict[date, tuple[Decimal, Decimal, int]]] = {}
    for currency, b, income, expense, n in db.execute(stmt).all():
        per_currency.setdefault(currency, {})[b.date()] = (money(income), money(expense), n)

    result = []
    for currency in sorted(per_currency):
        data = per_currency[currency]
        # Series runs over the requested range (or the data's own extent if
        # open-ended) with empty months filled as zeros, so "previous
        # month" always means the previous *calendar* month.
        first = month_start(scope.date_from) if scope.date_from else min(data)
        last = month_start(scope.date_to) if scope.date_to else max(data)

        points: list[MonthPoint] = []
        prev: tuple[Decimal, Decimal, Decimal] | None = None
        cursor = first
        while cursor <= last:
            income, expense, n = data.get(cursor, (ZERO, ZERO, 0))
            net = income - expense
            partial = bool(
                (scope.date_from and scope.date_from > cursor)
                or (scope.date_to and scope.date_to < month_end(cursor))
            )
            if prev is None:
                deltas = (None, None, None, None, None)
            else:
                p_income, p_expense, p_net = prev
                deltas = (
                    income - p_income,
                    pct(income - p_income, p_income),
                    expense - p_expense,
                    pct(expense - p_expense, p_expense),
                    net - p_net,
                )
            points.append(MonthPoint(cursor, income, expense, net, n, partial, *deltas))
            prev = (income, expense, net)
            cursor = next_month(cursor)
        result.append(CurrencyMonthly(currency=currency, months=points))
    return result
