"""Python mirror of ReconciliationService.compare."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .rules import expected_billing_status


@dataclass(frozen=True)
class Line:
    line_key: str
    product_code: str
    quantity: Decimal
    unit_price: Decimal


@dataclass(frozen=True)
class Drift:
    kind: str
    line_key: str | None
    salesforce_value: str | None
    billing_value: str | None


def fmt(d: Decimal | None) -> str:
    return "null" if d is None else str(Decimal(d).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compare(sf_status: str, sf_lines: list[Line], billing_status: str | None, billing_lines: list[Line] | None) -> list[Drift]:
    out: list[Drift] = []
    expected = expected_billing_status(sf_status)
    if billing_status is None:
        if expected is not None:
            out.append(Drift("Missing_In_Billing", None, sf_status, "404"))
        return out
    if expected != billing_status:
        out.append(Drift("Status_Mismatch", None, sf_status, billing_status))
    if billing_status == "cancelled" and expected == "cancelled":
        return out

    sf = {line.line_key: line for line in sf_lines}
    billing = {line.line_key: line for line in (billing_lines or [])}
    for key in sorted(sf):
        s, b = sf[key], billing.get(key)
        if b is None:
            out.append(Drift("Missing_In_Billing", key, f"{fmt(s.quantity)} @ {fmt(s.unit_price)}", None))
            continue
        if fmt(s.quantity) != fmt(b.quantity):
            out.append(Drift("Quantity_Mismatch", key, fmt(s.quantity), fmt(b.quantity)))
        if fmt(s.unit_price) != fmt(b.unit_price):
            out.append(Drift("Price_Mismatch", key, fmt(s.unit_price), fmt(b.unit_price)))
    for key in sorted(billing):
        if key not in sf:
            b = billing[key]
            out.append(Drift("Missing_In_Salesforce", key, None, f"{fmt(b.quantity)} @ {fmt(b.unit_price)}"))
    return out
