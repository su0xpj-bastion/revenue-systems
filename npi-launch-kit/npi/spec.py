"""Pricing & packaging spec: the one input every NPI step reads.

A launch is written once as a spec (YAML). Catalog rows, scenario tests, readiness items,
migration plans and reconciliation checks are all derived from it, so they cannot drift apart.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

MODELS = ("flat", "per_seat", "usage_tiered", "committed")
BILLING_MONTHS = {"monthly": 1, "quarterly": 3, "annual": 12}
REVENUE_TREATMENTS = ("ratable", "usage", "point_in_time")
TIER_MODES = ("graduated", "volume")
MIGRATION_POLICIES = (
    "grandfather_until_end_of_renewal",  # keep old SKU + price until end_of_renewal
    "migrate_at_renewal",                # move to replacement at next renewal
    "migrate_now_coterm",                # amend now, co-termed to current end date
)
SIGNOFF_TEAMS = (
    "product", "pricing", "deal_desk", "sales", "finance",
    "accounting", "tax", "legal", "billing_eng",
)
REQUIRED_SIGNOFFS = ("finance", "tax", "legal", "deal_desk", "billing_eng")


class SpecError(ValueError):
    """The spec cannot be parsed at all (as opposed to lint findings, which can)."""


def dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def as_date(value) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise SpecError(f"not an ISO date: {value!r}") from exc


@dataclass(frozen=True)
class Tier:
    up_to: Decimal | None  # None = unbounded (last tier only)
    price: Decimal


@dataclass(frozen=True)
class RampYear:
    year: int
    commit: Decimal


@dataclass
class Product:
    sku: str
    name: str
    model: str
    family: str = ""
    billing_frequency: str | None = None
    tax_code: str | None = None
    revenue: str | None = None
    term_months: int = 12
    list_price: Decimal | None = None      # flat: per month; per_seat: per seat per month
    min_quantity: int = 1
    unit: str | None = None                # usage unit, e.g. "1M tokens"
    usage_source: str | None = None        # system of record for usage quantities
    tier_mode: str | None = None
    tiers: list[Tier] = field(default_factory=list)
    ramp: list[RampYear] = field(default_factory=list)
    drawdown_rate: Decimal | None = None   # committed: value per unit drawn from the commit
    overage_rate: Decimal | None = None    # committed: price per unit beyond the commit
    usage_sku: str | None = None           # committed: which metered SKU draws down


@dataclass
class Bundle:
    sku: str
    name: str
    required: list[str]
    optional: list[str]


@dataclass(frozen=True)
class ApprovalBand:
    max_discount_pct: Decimal
    approver: str


@dataclass
class Retirement:
    sku: str
    replacement: str
    end_of_sale: date      # no new business after this date
    end_of_renewal: date   # no renewals on this SKU after this date
    policy: str


@dataclass
class Launch:
    code: str
    name: str
    launch_date: date
    first_bill_run: date
    currency: str
    products: list[Product]
    bundles: list[Bundle] = field(default_factory=list)
    approvals: list[ApprovalBand] = field(default_factory=list)
    retirements: list[Retirement] = field(default_factory=list)
    signoffs: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    def product(self, sku: str) -> Product | None:
        return next((p for p in self.products if p.sku == sku), None)


def _require(data: dict, key: str, where: str):
    if data.get(key) in (None, ""):
        raise SpecError(f"{where}: missing required field {key!r}")
    return data[key]


def parse_product(raw: dict) -> Product:
    where = f"product {raw.get('sku', '?')}"
    return Product(
        sku=_require(raw, "sku", where),
        name=_require(raw, "name", where),
        model=_require(raw, "model", where),
        family=raw.get("family") or "",
        billing_frequency=raw.get("billing_frequency"),
        tax_code=raw.get("tax_code"),
        revenue=raw.get("revenue"),
        term_months=int(raw.get("term_months") or 12),
        list_price=dec(raw.get("list_price")),
        min_quantity=int(raw.get("min_quantity") or 1),
        unit=raw.get("unit"),
        usage_source=raw.get("usage_source"),
        tier_mode=raw.get("tier_mode"),
        tiers=[Tier(dec(t.get("up_to")), dec(t["price"])) for t in raw.get("tiers") or []],
        ramp=[RampYear(int(r["year"]), dec(r["commit"])) for r in raw.get("ramp") or []],
        drawdown_rate=dec(raw.get("drawdown_rate")),
        overage_rate=dec(raw.get("overage_rate")),
        usage_sku=raw.get("usage_sku"),
    )


def parse_spec(data: dict) -> Launch:
    launch = data.get("launch") or {}
    return Launch(
        code=_require(launch, "code", "launch"),
        name=_require(launch, "name", "launch"),
        launch_date=as_date(_require(launch, "launch_date", "launch")),
        first_bill_run=as_date(_require(launch, "first_bill_run", "launch")),
        currency=launch.get("currency") or "USD",
        products=[parse_product(p) for p in data.get("products") or []],
        bundles=[
            Bundle(b["sku"], b["name"], list(b.get("required") or []), list(b.get("optional") or []))
            for b in data.get("bundles") or []
        ],
        approvals=[
            ApprovalBand(dec(a["max_discount_pct"]), a["approver"])
            for a in data.get("approvals") or []
        ],
        retirements=[
            Retirement(
                sku=r["sku"],
                replacement=r["replacement"],
                end_of_sale=as_date(r["end_of_sale"]),
                end_of_renewal=as_date(r["end_of_renewal"]),
                policy=r["policy"],
            )
            for r in data.get("retirements") or []
        ],
        signoffs=list(data.get("signoffs") or []),
        open_questions=list(data.get("open_questions") or []),
    )


def load_spec(path: Path) -> Launch:
    with Path(path).open("r", encoding="utf-8") as f:
        return parse_spec(yaml.safe_load(f))
