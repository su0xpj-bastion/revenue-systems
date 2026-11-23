"""Existing-customer impact of retiring SKUs: who moves, when, at what price, and what breaks.

Input: an export of active subscriptions (account, subscription_id, sku, quantity,
unit_price per month, start_date, end_date). Output: one plan row per affected subscription,
with flags for Customer Success, Deal Desk and Finance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .pricing import add_months, coterm_proration, money
from .spec import Launch, Retirement

UPLIFT_OUTREACH_PCT = Decimal(10)   # price increases above this need CS outreach before renewal notice


@dataclass
class PlanRow:
    account: str
    subscription_id: str
    sku: str
    replacement: str
    policy: str
    action: str
    effective: date
    old_monthly: Decimal
    new_monthly: Decimal
    uplift_pct: Decimal
    amendment_net: Decimal | None = None
    flags: list[str] = field(default_factory=list)


def plan_migrations(launch: Launch, subscriptions: list[dict], as_of: date) -> list[PlanRow]:
    by_sku: dict[str, Retirement] = {r.sku: r for r in launch.retirements}
    rows: list[PlanRow] = []
    for sub in subscriptions:
        retirement = by_sku.get(sub["sku"])
        if retirement is None:
            continue
        replacement = launch.product(retirement.replacement)
        qty = Decimal(sub["quantity"])
        old_unit = Decimal(sub["unit_price"])
        end = date.fromisoformat(sub["end_date"])
        new_unit = replacement.list_price or Decimal(0)
        old_monthly, new_monthly = money(old_unit * qty), money(new_unit * qty)
        uplift = (
            ((new_monthly - old_monthly) / old_monthly * 100).quantize(Decimal("0.1"))
            if old_monthly else Decimal(0)
        )
        flags: list[str] = []
        amendment_net = None

        if retirement.policy == "grandfather_until_end_of_renewal":
            effective = end
            while effective < retirement.end_of_renewal:
                # each renewal stays on the old SKU while renewals are still allowed
                effective = add_months(effective, 12)
            action = f"renew on {sub['sku']} at current price until {effective}, then move to {replacement.sku}"
        elif retirement.policy == "migrate_at_renewal":
            effective = end
            action = f"renew onto {replacement.sku} at {end}"
            if end > retirement.end_of_renewal:
                flags.append("term ends after end_of_renewal; renewal would need a retired SKU")
        else:  # migrate_now_coterm
            effective = max(as_of, retirement.end_of_sale)
            credit = coterm_proration(old_unit, qty, effective, end)
            charge = coterm_proration(new_unit, qty, effective, end)
            amendment_net = charge - credit
            action = (f"amend on {effective}: remove {sub['sku']} (credit {credit}), "
                      f"add {replacement.sku} co-termed to {end} (charge {charge})")

        if qty < replacement.min_quantity:
            flags.append(f"{qty} seats is below {replacement.sku} minimum {replacement.min_quantity}")
        if uplift > UPLIFT_OUTREACH_PCT:
            flags.append(f"price uplift {uplift}%: CS outreach before renewal notice")
        if replacement.tax_code != sub.get("tax_code", replacement.tax_code):
            flags.append("tax code changes on migration; confirm with Tax")

        rows.append(PlanRow(
            account=sub["account"], subscription_id=sub["subscription_id"], sku=sub["sku"],
            replacement=replacement.sku, policy=retirement.policy, action=action,
            effective=effective, old_monthly=old_monthly, new_monthly=new_monthly,
            uplift_pct=uplift, amendment_net=amendment_net, flags=flags,
        ))
    return rows


def summarize(rows: list[PlanRow]) -> dict:
    return {
        "subscriptions": len(rows),
        "flagged": sum(1 for r in rows if r.flags),
        "monthly_revenue_before": str(sum((r.old_monthly for r in rows), Decimal(0))),
        "monthly_revenue_after": str(sum((r.new_monthly for r in rows), Decimal(0))),
    }
