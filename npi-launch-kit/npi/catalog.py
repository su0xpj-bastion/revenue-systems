"""Spec → catalog change set: the load files and the plan a reviewer signs.

Outputs one CSV per target, ready for Data Loader / sf data import after review:
  Product2, PricebookEntry                    standard Salesforce
  SBQQ__DiscountSchedule__c / DiscountTier    Salesforce CPQ tiers (graduated = Slab, volume = Range)
  SBQQ__ProductOption__c                      CPQ bundle options
  approval_rules, billing_plans, tax_mappings, reporting_map   handoffs to Deal Desk,
                                              Billing Engineering, Tax and Finance

CPQ field API names follow the SBQQ package; confirm them against the org's installed version
before loading.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .pricing import money
from .spec import Launch, Product


def fmt(value: Decimal) -> str:
    return str(money(value))

BILLING_MODEL_LABEL = {
    "flat": "Flat",
    "per_seat": "Per Seat",
    "usage_tiered": "Usage",
    "committed": "Committed",
}
CHARGE_TYPE = {"flat": "Recurring", "per_seat": "Recurring", "usage_tiered": "Usage", "committed": "Recurring"}
PRICEBOOK_PRICE_FIELDS = ("UnitPrice",)


def _unit_price(p: Product) -> Decimal:
    if p.model in ("flat", "per_seat"):
        return p.list_price
    if p.model == "usage_tiered":
        return p.tiers[0].price if p.tiers else Decimal(0)
    return p.ramp[0].commit if p.ramp else Decimal(0)


def build_catalog(launch: Launch) -> dict[str, list[dict]]:
    retiring = {r.sku: r for r in launch.retirements}
    tables: dict[str, list[dict]] = {
        "Product2": [], "PricebookEntry": [], "SBQQ__DiscountSchedule__c": [],
        "SBQQ__DiscountTier__c": [], "SBQQ__ProductOption__c": [], "approval_rules": [],
        "billing_plans": [], "tax_mappings": [], "reporting_map": [],
    }

    for p in launch.products:
        tables["Product2"].append({
            "ProductCode": p.sku,
            "Name": p.name,
            "Family": p.family,
            "IsActive": "true",
            "Billing_Model__c": BILLING_MODEL_LABEL[p.model],
            "Tax_Code__c": p.tax_code or "",
            "Launch_Stage__c": "Planned",
            "End_of_Sale_Date__c": "",
            "SBQQ__ChargeType__c": CHARGE_TYPE[p.model],
            "SBQQ__BillingFrequency__c": (p.billing_frequency or "").capitalize(),
            "SBQQ__SubscriptionTerm__c": p.term_months,
            "SBQQ__SubscriptionPricing__c": "Fixed Price",
            "SBQQ__PricingMethod__c": "List",
        })
        tables["PricebookEntry"].append({
            "ProductCode": p.sku, "Pricebook": "Standard Price Book",
            "CurrencyIsoCode": launch.currency, "UnitPrice": fmt(_unit_price(p)), "IsActive": "true",
        })
        if p.model == "usage_tiered":
            schedule = f"{p.sku} {p.tier_mode} tiers"
            tables["SBQQ__DiscountSchedule__c"].append({
                "Name": schedule, "SBQQ__Product__c": p.sku,
                "SBQQ__Type__c": "Slab" if p.tier_mode == "graduated" else "Range",
                "SBQQ__DiscountUnit__c": "Price",
            })
            lower = Decimal(0)
            for i, tier in enumerate(p.tiers, start=1):
                tables["SBQQ__DiscountTier__c"].append({
                    "SBQQ__Schedule__c": schedule, "Name": f"Tier {i}",
                    "SBQQ__LowerBound__c": str(lower),
                    "SBQQ__UpperBound__c": "" if tier.up_to is None else str(tier.up_to),
                    "SBQQ__Price__c": fmt(tier.price),
                })
                lower = tier.up_to if tier.up_to is not None else lower
        tables["billing_plans"].append({
            "sku": p.sku,
            "charge": {"usage_tiered": "usage in arrears", "committed": "commit in advance + overage in arrears"}
                      .get(p.model, "recurring in advance"),
            "frequency": p.billing_frequency or "",
            "term_months": p.term_months,
            "unit": p.unit or "",
            "usage_source": p.usage_source or ("" if p.model != "committed" else f"via {p.usage_sku}"),
            "ramp": ";".join(f"Y{r.year}={r.commit}" for r in p.ramp),
            "drawdown_rate": "" if p.drawdown_rate is None else str(p.drawdown_rate),
            "overage_rate": "" if p.overage_rate is None else str(p.overage_rate),
        })
        tables["tax_mappings"].append({"sku": p.sku, "name": p.name, "tax_code": p.tax_code or "MISSING"})
        tables["reporting_map"].append({
            "sku": p.sku, "family": p.family, "revenue_treatment": p.revenue or "",
            "booking_metric": {"usage_tiered": "consumption (not booked)", "committed": "ACV = ramp year commit"}
                              .get(p.model, "ACV = 12 x monthly price x quantity"),
        })

    for b in launch.bundles:
        tables["Product2"].append({
            "ProductCode": b.sku, "Name": b.name, "IsActive": "true",
            "Billing_Model__c": "Bundle", "Launch_Stage__c": "Planned",
            "SBQQ__ConfigurationType__c": "Allowed", "SBQQ__ConfigurationEvent__c": "Always",
        })
        tables["PricebookEntry"].append({
            "ProductCode": b.sku, "Pricebook": "Standard Price Book",
            "CurrencyIsoCode": launch.currency, "UnitPrice": "0", "IsActive": "true",
        })
        for number, sku in enumerate(b.required + b.optional, start=1):
            tables["SBQQ__ProductOption__c"].append({
                "SBQQ__ConfiguredSKU__c": b.sku, "SBQQ__OptionalSKU__c": sku,
                "SBQQ__Number__c": number * 10,
                "SBQQ__Required__c": "true" if sku in b.required else "false",
                "SBQQ__Selected__c": "true" if sku in b.required else "false",
            })

    previous = Decimal(0)
    for band in launch.approvals:
        tables["approval_rules"].append({
            "rule": f"Discount {previous}%–{band.max_discount_pct}%",
            "condition": f"max line discount > {previous}% and <= {band.max_discount_pct}%",
            "approver": band.approver,
        })
        previous = band.max_discount_pct
    tables["approval_rules"].append({
        "rule": f"Discount above {previous}%", "condition": f"max line discount > {previous}%",
        "approver": "reject (cannot be quoted)",
    })

    for r in retiring.values():
        tables["Product2"].append({
            "ProductCode": r.sku, "Launch_Stage__c": "End of Sale",
            "End_of_Sale_Date__c": r.end_of_sale.isoformat(),
        })
    return tables


def write_tables(tables: dict[str, list[dict]], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, rows in tables.items():
        if not rows:
            continue
        headers = list(dict.fromkeys(k for row in rows for k in row))
        path = out_dir / f"{name}.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        written.append(path)
    return written


@dataclass(frozen=True)
class Change:
    action: str        # ADD | CHANGE | END_OF_SALE | UNCHANGED
    sku: str
    detail: str


def diff_catalog(launch: Launch, current_rows: list[dict]) -> list[Change]:
    """Compare the spec with the live catalog export (ProductCode, Name, UnitPrice, Tax_Code__c, IsActive)."""
    current = {row["ProductCode"]: row for row in current_rows}
    changes: list[Change] = []
    for p in launch.products:
        row = current.get(p.sku)
        if row is None:
            changes.append(Change("ADD", p.sku, f"new {p.model} product {p.name!r}"))
            continue
        diffs = []
        if row.get("Name") != p.name:
            diffs.append(f"Name {row.get('Name')!r} → {p.name!r}")
        if row.get("UnitPrice") and Decimal(row["UnitPrice"]) != _unit_price(p):
            diffs.append(f"UnitPrice {row['UnitPrice']} → {fmt(_unit_price(p))} (affects renewals priced from list)")
        if (row.get("Tax_Code__c") or None) != p.tax_code:
            diffs.append(f"Tax_Code__c {row.get('Tax_Code__c')!r} → {p.tax_code!r}")
        changes.append(Change("CHANGE" if diffs else "UNCHANGED", p.sku, "; ".join(diffs) or "no change"))
    for r in launch.retirements:
        if r.sku not in current:
            changes.append(Change("END_OF_SALE", r.sku, "WARNING: not in current catalog export"))
        else:
            changes.append(Change(
                "END_OF_SALE", r.sku,
                f"no new sales from {r.end_of_sale}, no renewals after {r.end_of_renewal}, "
                f"replacement {r.replacement}, policy {r.policy}",
            ))
    return changes


def read_csv(path: Path) -> list[dict]:
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
