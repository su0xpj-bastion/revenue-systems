"""Billing run for one period: rate usage, build invoices, tax them, finalize immutably.

Rules:
- Seats and flat fees bill in advance: monthly each period, or annually on each contract anniversary.
- Usage bills in arrears for every unbilled event timestamped before the period end. Late events
  from an already-billed period are billed here, labeled as prior-period usage.
- A prepaid commit invoices in full in the contract's first period. Usage under the commit is
  shown at list price with a matching negative "credit applied" line, so the customer sees the drawdown.
- Finalized invoices are never edited. Each is stored as canonical JSON with its SHA-256.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from .model import Book, Contract, Product, add_months, money, period_bounds, period_of
from .rating import rate_usage
from .store import Store
from .tax import TaxProvider


class BillingError(RuntimeError):
    pass


@dataclass
class Line:
    kind: str               # subscription | prepaid_commit | usage | credit_applied
    product: str
    description: str
    quantity: str
    amount: str
    tax_code: str
    service_start: str
    service_end: str
    tax: str = "0.00"
    tax_note: str = ""


def digest(body: dict) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def credit_used(store: Store, contract_id: str) -> Decimal:
    return -sum(
        (Decimal(l["amount"]) for inv in store.invoices() if inv["contract_id"] == contract_id
         for l in inv["lines"] if l["kind"] == "credit_applied"),
        Decimal(0),
    )


def _recurring_lines(contract: Contract, book: Book, start: date, end: date) -> list[Line]:
    lines = []
    for cl in contract.lines:
        product = book.products[cl.product]
        if product.kind not in ("seat", "flat"):
            continue
        qty = cl.quantity if product.kind == "seat" else Decimal(1)
        if cl.billing == "monthly":
            if contract.start <= start and end <= contract.end:
                lines.append(Line(
                    "subscription", product.code, f"{product.name} ({qty} x {money(product.unit_price)}/mo)",
                    str(qty), str(money(qty * product.unit_price)), product.tax_code,
                    start.isoformat(), end.isoformat(),
                ))
            continue
        years = 0
        while (anniversary := add_months(contract.start, 12 * years)) < contract.end:
            if start <= anniversary < end:
                service_end = min(add_months(anniversary, 12), contract.end)
                months = (service_end.year - anniversary.year) * 12 + service_end.month - anniversary.month
                lines.append(Line(
                    "subscription", product.code,
                    f"{product.name} ({qty} x {money(product.unit_price)}/mo x {months} mo, annual in advance)",
                    str(qty), str(money(qty * product.unit_price * months)), product.tax_code,
                    anniversary.isoformat(), service_end.isoformat(),
                ))
            years += 1
    return lines


def _usage_lines(contract: Contract, book: Book, store: Store, start: date, end: date,
                 credit_balance: Decimal) -> tuple[list[Line], list[str], Decimal]:
    lines: list[Line] = []
    billed_events: list[str] = []
    for cl in contract.lines:
        product: Product = book.products[cl.product]
        if product.kind != "usage":
            continue
        events = store.unbilled_events(contract.customer, product.meter, end.isoformat())
        events = [e for e in events if e["ts"] >= contract.start.isoformat()]
        if not events:
            continue
        quantity = sum((Decimal(e["quantity"]) for e in events), Decimal(0))
        late = sum((Decimal(e["quantity"]) for e in events if e["ts"] < start.isoformat()), Decimal(0))
        amount = money(rate_usage(product, quantity))
        note = f" incl. {late} prior-period (late) {product.unit}" if late else ""
        lines.append(Line(
            "usage", product.code, f"{product.name}: {quantity} {product.unit}{note}",
            str(quantity), str(amount), product.tax_code, start.isoformat(), end.isoformat(),
        ))
        billed_events += [e["event_id"] for e in events]
        if contract.commit and product.code in contract.commit.applies_to and credit_balance > 0:
            applied = min(credit_balance, amount)
            credit_balance -= applied
            lines.append(Line(
                "credit_applied", product.code, f"Prepaid commit applied (remaining {credit_balance})",
                "1", str(-applied), product.tax_code, start.isoformat(), end.isoformat(),
            ))
    return lines, billed_events, credit_balance


def build_invoices(book: Book, store: Store, period: str, tax: TaxProvider) -> tuple[list[dict], dict[str, str]]:
    start, end = period_bounds(period)
    invoices, event_bills = [], {}
    for contract in book.contracts:
        if not (contract.start < end and contract.end > start):
            continue
        customer = book.customers[contract.customer]
        lines = _recurring_lines(contract, book, start, end)
        balance = Decimal(0)
        if contract.commit:
            balance = contract.commit.amount - credit_used(store, contract.id)
            if period_of(contract.start) == period:
                drawdown = book.products[contract.commit.applies_to[0]]
                lines.append(Line(
                    "prepaid_commit", drawdown.code, f"Prepaid usage commit {contract.start} to {contract.end}",
                    "1", str(money(contract.commit.amount)), drawdown.tax_code,
                    contract.start.isoformat(), contract.end.isoformat(),
                ))
        usage, billed, _ = _usage_lines(contract, book, store, start, end, balance)
        lines += usage
        if not lines:
            continue
        invoice_id = f"INV-{period}-{contract.id}"
        for line in lines:
            amount, note = tax.tax_line(customer, line.tax_code, Decimal(line.amount))
            line.tax, line.tax_note = str(amount), note
        subtotal = money(sum((Decimal(l.amount) for l in lines), Decimal(0)))
        tax_total = money(sum((Decimal(l.tax) for l in lines), Decimal(0)))
        invoices.append({
            "invoice_id": invoice_id, "contract_id": contract.id, "customer_id": customer.id,
            "period": period, "lines": [asdict(l) for l in lines],
            "subtotal": str(subtotal), "tax": str(tax_total), "total": str(subtotal + tax_total),
        })
        event_bills.update({event_id: invoice_id for event_id in billed})
    return invoices, event_bills


def run_billing(book: Book, store: Store, period: str, tax: TaxProvider) -> list[dict]:
    if store.period_billed(period):
        raise BillingError(f"{period} is already billed; corrections go through credit notes")
    later = [p for p in store.billed_periods() if p > period]
    if later:
        raise BillingError(f"cannot bill {period} after later periods {later}")
    invoices, event_bills = build_invoices(book, store, period, tax)
    store.save_run(period, [(inv, digest(inv)) for inv in invoices], event_bills)
    return invoices
