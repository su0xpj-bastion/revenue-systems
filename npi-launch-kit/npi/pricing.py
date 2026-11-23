"""Reference pricing engine: what SHOULD be invoiced for a quote.

This is the independent oracle that quote and billing scenario tests compare against.
Money is Decimal, rounded half-up to cents per invoice line.

Conventions (written down because each is a real design decision):
- Recurring (flat, per_seat) charges bill in advance, once per billing period.
- Usage bills monthly in arrears at the tier price; graduated = each tier's units at its own
  price, volume = all units at the price of the tier the total lands in.
- Committed: the year's commit bills in advance at the start of each contract year. Usage of
  `usage_sku` draws the commit down at `drawdown_rate`; once it is used up, extra units bill in
  arrears at `overage_rate`. Unused commit does not roll over.
- A line's discount applies to every charge on that line.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .spec import BILLING_MONTHS, Launch, Product, Tier

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year, month = d.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def tiered_amount(quantity: Decimal, tiers: list[Tier], mode: str) -> Decimal:
    if quantity <= 0:
        return Decimal(0)
    if mode == "volume":
        for tier in tiers:
            if tier.up_to is None or quantity <= tier.up_to:
                return quantity * tier.price
        raise ValueError("quantity exceeds the last tier")
    total, lower = Decimal(0), Decimal(0)
    for tier in tiers:
        if tier.up_to is None or quantity <= tier.up_to:
            return total + (quantity - lower) * tier.price
        total += (tier.up_to - lower) * tier.price
        lower = tier.up_to
    raise ValueError("quantity exceeds the last tier")


@dataclass(frozen=True)
class QuoteLine:
    sku: str
    quantity: Decimal = Decimal(1)
    discount_pct: Decimal = Decimal(0)


@dataclass(frozen=True)
class InvoiceLine:
    period_start: date
    sku: str
    kind: str          # recurring | usage | commit | overage
    quantity: Decimal
    amount: Decimal


def _factor(line: QuoteLine) -> Decimal:
    return (Decimal(100) - line.discount_pct) / Decimal(100)


def invoice_schedule(
    launch: Launch,
    lines: list[QuoteLine],
    start: date,
    usage: dict[str, list[Decimal]] | None = None,
) -> list[InvoiceLine]:
    usage = usage or {}
    committed_usage = {launch.product(l.sku).usage_sku for l in lines
                       if launch.product(l.sku) and launch.product(l.sku).model == "committed"}
    invoices: list[InvoiceLine] = []
    for line in lines:
        product = launch.product(line.sku)
        if product is None:
            raise ValueError(f"{line.sku} is not in the launch catalog")
        if product.model == "usage_tiered" and product.sku in committed_usage:
            raise ValueError(
                f"{product.sku} is quoted pay-as-you-go and also draws down a commit on the same quote"
            )
        invoices.extend(_line_invoices(product, line, start, usage, launch))
    return sorted(invoices, key=lambda i: (i.period_start, i.sku, i.kind))


def _line_invoices(product: Product, line: QuoteLine, start: date, usage, launch) -> list[InvoiceLine]:
    out: list[InvoiceLine] = []
    factor = _factor(line)

    if product.model in ("flat", "per_seat"):
        if product.model == "per_seat" and line.quantity < product.min_quantity:
            raise ValueError(f"{product.sku}: {line.quantity} seats is below minimum {product.min_quantity}")
        step = BILLING_MONTHS[product.billing_frequency]
        for month in range(0, product.term_months, step):
            amount = product.list_price * line.quantity * step * factor
            out.append(InvoiceLine(add_months(start, month), product.sku, "recurring",
                                   line.quantity, money(amount)))

    elif product.model == "usage_tiered":
        for month, units in enumerate(usage.get(product.sku, [])[: product.term_months]):
            units = Decimal(str(units))
            amount = tiered_amount(units, product.tiers, product.tier_mode) * factor
            out.append(InvoiceLine(add_months(start, month), product.sku, "usage", units, money(amount)))

    elif product.model == "committed":
        metered = [Decimal(str(u)) for u in usage.get(product.usage_sku, [])]
        for index, ramp in enumerate(product.ramp):
            year_start = add_months(start, 12 * index)
            out.append(InvoiceLine(year_start, product.sku, "commit", Decimal(1),
                                   money(ramp.commit * factor)))
            consumed = Decimal(0)
            for month in range(12):
                position = 12 * index + month
                if position >= len(metered):
                    break
                units = metered[position]
                value = units * product.drawdown_rate
                if consumed + value <= ramp.commit:
                    consumed += value
                    continue
                covered_units = (ramp.commit - consumed) / product.drawdown_rate
                consumed = ramp.commit
                overage_units = units - covered_units
                out.append(InvoiceLine(add_months(year_start, month), product.sku, "overage",
                                       overage_units, money(overage_units * product.overage_rate * factor)))
    return out


def coterm_proration(monthly_price: Decimal, quantity: Decimal, amend_date: date, end_date: date) -> Decimal:
    """Monthly + daily proration to an existing end date (end exclusive): whole months, then
    the leftover days as a fraction of the month they fall in. Matches common CPQ defaults."""
    if amend_date >= end_date:
        return Decimal(0)
    months = 0
    while add_months(amend_date, months + 1) <= end_date:
        months += 1
    cursor = add_months(amend_date, months)
    days_in_month = calendar.monthrange(cursor.year, cursor.month)[1]
    fraction = Decimal(months) + Decimal((end_date - cursor).days) / Decimal(days_in_month)
    return money(monthly_price * quantity * fraction)


def approver_for(launch: Launch, discount_pct: Decimal) -> str:
    """Lowest band whose cap covers the discount; beyond the top band the deal is rejected."""
    for band in launch.approvals:
        if discount_pct <= band.max_discount_pct:
            return band.approver
    return "reject"
