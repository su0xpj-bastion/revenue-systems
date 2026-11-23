"""Catalog, customers, contracts and tax rates: the reference data billing runs against."""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def add_months(d: date, months: int) -> date:
    index = d.month - 1 + months
    year, month = d.year + index // 12, index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


# --- periods ("YYYY-MM", calendar months, end exclusive) -----------------------

def period_bounds(period: str) -> tuple[date, date]:
    start = date.fromisoformat(f"{period}-01")
    return start, add_months(start, 1)


def period_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def periods_between(start: date, end: date) -> list[str]:
    """Calendar periods overlapping [start, end)."""
    out, cursor = [], date(start.year, start.month, 1)
    while cursor < end:
        out.append(period_of(cursor))
        cursor = add_months(cursor, 1)
    return out


# --- reference data -----------------------------------------------------------

@dataclass(frozen=True)
class Tier:
    up_to: Decimal | None
    unit_price: Decimal


@dataclass
class Product:
    code: str
    name: str
    kind: str                       # seat | flat | usage
    tax_code: str
    unit_price: Decimal | None = None
    meter: str | None = None
    unit: str | None = None
    tier_mode: str | None = None    # graduated | volume
    tiers: list[Tier] = field(default_factory=list)


@dataclass
class Customer:
    id: str
    name: str
    jurisdiction: str               # e.g. US-NY
    exemption_certificate: str | None = None


@dataclass
class ContractLine:
    product: str
    quantity: Decimal = Decimal(1)
    billing: str = "monthly"        # monthly | annual (in advance)


@dataclass
class Commit:
    amount: Decimal                 # prepaid, invoiced at contract start
    applies_to: list[str]           # usage products it draws down


@dataclass
class Contract:
    id: str
    customer: str
    start: date
    end: date                       # exclusive
    lines: list[ContractLine]
    commit: Commit | None = None


@dataclass
class Book:
    products: dict[str, Product]
    customers: dict[str, Customer]
    contracts: list[Contract]
    tax_rates: dict[str, dict[str, Decimal]]

    def product_for_meter(self, meter: str) -> Product | None:
        return next((p for p in self.products.values() if p.meter == meter), None)


class BookError(ValueError):
    pass


def _load_yaml(path: Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_book(directory: Path) -> Book:
    directory = Path(directory)
    catalog = _load_yaml(directory / "catalog.yaml")
    accounts = _load_yaml(directory / "contracts.yaml")
    taxes = _load_yaml(directory / "tax_rates.yaml")

    products = {}
    for raw in catalog["products"]:
        products[raw["code"]] = Product(
            code=raw["code"], name=raw["name"], kind=raw["kind"], tax_code=raw["tax_code"],
            unit_price=dec(raw.get("unit_price")), meter=raw.get("meter"), unit=raw.get("unit"),
            tier_mode=raw.get("tier_mode"),
            tiers=[Tier(dec(t.get("up_to")), dec(t["unit_price"])) for t in raw.get("tiers") or []],
        )
    customers = {
        c["id"]: Customer(c["id"], c["name"], c["jurisdiction"], c.get("exemption_certificate"))
        for c in accounts["customers"]
    }
    contracts = []
    for raw in accounts["contracts"]:
        commit = raw.get("commit")
        contracts.append(Contract(
            id=raw["id"], customer=raw["customer"],
            start=as_date(raw["start"]), end=as_date(raw["end"]),
            lines=[ContractLine(l["product"], dec(l.get("quantity", 1)), l.get("billing", "monthly"))
                   for l in raw["lines"]],
            commit=Commit(dec(commit["amount"]), list(commit["applies_to"])) if commit else None,
        ))
    rates = {j: {code: dec(r) for code, r in codes.items()} for j, codes in taxes["rates"].items()}
    book = Book(products, customers, contracts, rates)
    validate_book(book)
    return book


def validate_book(book: Book) -> None:
    problems = []
    for c in book.contracts:
        if c.customer not in book.customers:
            problems.append(f"{c.id}: unknown customer {c.customer}")
        if c.start.day != 1 or c.end.day != 1 or c.end <= c.start:
            problems.append(f"{c.id}: contracts start and end on the 1st, end after start")
        for line in c.lines:
            product = book.products.get(line.product)
            if product is None:
                problems.append(f"{c.id}: unknown product {line.product}")
            elif line.billing == "annual" and product.kind == "usage":
                problems.append(f"{c.id}: usage cannot be billed annually in advance")
        if c.commit:
            for code in c.commit.applies_to:
                if code not in book.products or book.products[code].kind != "usage":
                    problems.append(f"{c.id}: commit applies to non-usage product {code}")
    for p in book.products.values():
        if p.kind == "usage" and (not p.meter or not p.tiers or p.tiers[-1].up_to is not None):
            problems.append(f"{p.code}: usage product needs a meter and tiers ending in up_to: null")
        if p.kind in ("seat", "flat") and not p.unit_price:
            problems.append(f"{p.code}: needs unit_price")
    if problems:
        raise BookError("; ".join(problems))
