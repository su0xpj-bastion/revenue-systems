"""Tax calculation behind a provider interface.

`RateTableProvider` is a deterministic stand-in for a tax engine (Avalara, Anrok, Stripe Tax),
keyed by customer jurisdiction and product tax code. Rates in the example are illustrative,
not tax advice. A real provider plugs in behind the same `tax_line` call.

Fail closed: an unknown jurisdiction or tax code raises, so an invoice cannot finalize with
silently-zero tax.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from .model import Customer, money


class TaxError(ValueError):
    pass


class TaxProvider(Protocol):
    def tax_line(self, customer: Customer, tax_code: str, amount: Decimal) -> tuple[Decimal, str]:
        """Return (tax amount, audit note)."""


class RateTableProvider:
    def __init__(self, rates: dict[str, dict[str, Decimal]]):
        self.rates = rates

    def tax_line(self, customer: Customer, tax_code: str, amount: Decimal) -> tuple[Decimal, str]:
        if customer.exemption_certificate:
            return Decimal("0.00"), f"exempt: certificate {customer.exemption_certificate}"
        table = self.rates.get(customer.jurisdiction)
        if table is None:
            raise TaxError(f"no tax rates for jurisdiction {customer.jurisdiction}")
        if tax_code not in table:
            raise TaxError(f"no rate for tax code {tax_code} in {customer.jurisdiction}")
        rate = table[tax_code]
        tax = money(amount * rate)
        return (tax if tax != 0 else Decimal("0.00")), f"{customer.jurisdiction} {tax_code} @ {rate}"
