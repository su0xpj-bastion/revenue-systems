"""Revenue recognition schedules, deferred revenue roll-forward, and GL journal entries.

Policy (simplified, ASC 606-style; confirm with Accounting before relying on it):
- Subscriptions: billed in advance into deferred revenue, recognized ratably by day over the
  service period. Rounding remainder goes to the last period, so schedules sum exactly.
- Usage: recognized in the period consumed, at the billed (list) amount.
- Prepaid commit: billed into deferred revenue. Usage covered by the commit releases deferred
  revenue (the credit_applied amount). Unused commit is recognized as breakage in the
  contract's last period, once that period is billed.

Journal per invoice:
    Dr Accounts Receivable   total
    Dr Deferred Revenue      credit applied
        Cr Deferred Revenue  subscriptions + prepaid commits
        Cr Revenue           usage at list
        Cr Tax Payable       tax
Journal per period (recognition):
    Dr Deferred Revenue / Cr Revenue   ratable subscription share + breakage
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .model import Book, money, period_bounds, period_of, periods_between

AR, DEFERRED, REVENUE, TAX = "Accounts Receivable", "Deferred Revenue", "Revenue", "Tax Payable"


def allocate_by_days(amount: Decimal, start: date, end: date) -> dict[str, Decimal]:
    total_days = (end - start).days
    periods = periods_between(start, end)
    out: dict[str, Decimal] = {}
    allocated = Decimal(0)
    for i, period in enumerate(periods):
        p_start, p_end = period_bounds(period)
        if i == len(periods) - 1:
            out[period] = amount - allocated
            break
        days = (min(end, p_end) - max(start, p_start)).days
        share = money(amount * days / total_days)
        out[period] = share
        allocated += share
    return out


@dataclass
class PeriodRevenue:
    period: str
    usage: Decimal = Decimal(0)
    subscription: Decimal = Decimal(0)
    breakage: Decimal = Decimal(0)
    deferred_billed: Decimal = Decimal(0)
    credit_released: Decimal = Decimal(0)

    @property
    def revenue(self) -> Decimal:
        return self.usage + self.subscription + self.breakage

    @property
    def deferred_released(self) -> Decimal:
        return self.subscription + self.credit_released + self.breakage


def schedules(book: Book, invoices: list[dict], through: str) -> dict[str, PeriodRevenue]:
    """Revenue by period for every period up to `through`, from finalized invoices."""
    billed_periods = {inv["period"] for inv in invoices}
    rows: dict[str, PeriodRevenue] = {}

    def row(period: str) -> PeriodRevenue:
        return rows.setdefault(period, PeriodRevenue(period))

    commits: dict[str, dict] = {}
    for inv in invoices:
        for line in inv["lines"]:
            amount = Decimal(line["amount"])
            if line["kind"] == "subscription":
                row(inv["period"]).deferred_billed += amount
                schedule = allocate_by_days(
                    amount, date.fromisoformat(line["service_start"]), date.fromisoformat(line["service_end"]))
                for period, share in schedule.items():
                    if period <= through:
                        row(period).subscription += share
            elif line["kind"] == "prepaid_commit":
                row(inv["period"]).deferred_billed += amount
                commits[inv["contract_id"]] = {"amount": amount, "used": Decimal(0),
                                               "end": date.fromisoformat(line["service_end"])}
            elif line["kind"] == "usage":
                row(inv["period"]).usage += amount
            elif line["kind"] == "credit_applied":
                row(inv["period"]).credit_released += -amount
                commits.setdefault(inv["contract_id"], {"amount": Decimal(0), "used": Decimal(0), "end": None})
                commits[inv["contract_id"]]["used"] += -amount

    for contract_id, c in commits.items():
        if c["end"] is None:
            continue
        last = period_of(date.fromordinal(c["end"].toordinal() - 1))
        if last <= through and last in billed_periods and c["amount"] > c["used"]:
            row(last).breakage += c["amount"] - c["used"]
    return dict(sorted((p, r) for p, r in rows.items() if p <= through))


@dataclass
class RollForward:
    period: str
    beginning: Decimal
    billed: Decimal
    released: Decimal

    @property
    def ending(self) -> Decimal:
        return self.beginning + self.billed - self.released


def roll_forward(book: Book, invoices: list[dict], through: str) -> list[RollForward]:
    out, balance = [], Decimal(0)
    for period, r in schedules(book, invoices, through).items():
        rf = RollForward(period, balance, r.deferred_billed, r.deferred_released)
        out.append(rf)
        balance = rf.ending
    return out


@dataclass
class JournalLine:
    account: str
    debit: Decimal = Decimal(0)
    credit: Decimal = Decimal(0)


@dataclass
class JournalEntry:
    period: str
    reference: str
    memo: str
    lines: list[JournalLine] = field(default_factory=list)

    @property
    def balanced(self) -> bool:
        return sum(l.debit for l in self.lines) == sum(l.credit for l in self.lines)


def journal(book: Book, invoices: list[dict], through: str) -> list[JournalEntry]:
    entries: list[JournalEntry] = []
    for inv in invoices:
        if inv["period"] > through:
            continue
        by_kind: dict[str, Decimal] = defaultdict(Decimal)
        for line in inv["lines"]:
            by_kind[line["kind"]] += Decimal(line["amount"])
        e = JournalEntry(inv["period"], inv["invoice_id"], f"Invoice {inv['invoice_id']}")
        e.lines.append(JournalLine(AR, debit=Decimal(inv["total"])))
        if by_kind["credit_applied"]:
            e.lines.append(JournalLine(DEFERRED, debit=-by_kind["credit_applied"]))
        deferred = by_kind["subscription"] + by_kind["prepaid_commit"]
        if deferred:
            e.lines.append(JournalLine(DEFERRED, credit=deferred))
        if by_kind["usage"]:
            e.lines.append(JournalLine(REVENUE, credit=by_kind["usage"]))
        if Decimal(inv["tax"]):
            e.lines.append(JournalLine(TAX, credit=Decimal(inv["tax"])))
        entries.append(e)
    for period, r in schedules(book, invoices, through).items():
        release = r.subscription + r.breakage
        if release:
            entries.append(JournalEntry(period, f"REVREC-{period}",
                                        f"Ratable recognition {r.subscription} + breakage {r.breakage}",
                                        [JournalLine(DEFERRED, debit=release), JournalLine(REVENUE, credit=release)]))
    return entries


def trial_balance(entries: list[JournalEntry], through: str, period: str | None = None) -> dict[str, Decimal]:
    """Net balance per account (debit positive). `period` limits to one period's activity."""
    balances: dict[str, Decimal] = defaultdict(Decimal)
    for e in entries:
        if e.period > through or (period and e.period != period):
            continue
        for l in e.lines:
            balances[l.account] += l.debit - l.credit
    return dict(balances)
