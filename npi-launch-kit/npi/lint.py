"""Push-back linter: find pricing ideas that cannot be quoted, billed, taxed or reported cleanly.

Each finding names the team to take it back to. `block` findings stop the launch until resolved;
`warn` findings need a conscious decision recorded in the spec review.
"""
from __future__ import annotations

from dataclasses import dataclass

from .spec import (
    BILLING_MONTHS,
    MIGRATION_POLICIES,
    MODELS,
    REQUIRED_SIGNOFFS,
    REVENUE_TREATMENTS,
    SIGNOFF_TEAMS,
    TIER_MODES,
    Launch,
    Product,
)


@dataclass(frozen=True)
class Finding:
    severity: str          # "block" | "warn"
    rule: str
    message: str
    push_back_to: str      # team that owns the decision
    sku: str | None = None

    def __str__(self) -> str:
        where = f"[{self.sku}] " if self.sku else ""
        return f"{self.severity.upper():5} {self.rule}: {where}{self.message} → {self.push_back_to}"


def lint(launch: Launch) -> list[Finding]:
    findings: list[Finding] = []
    add = lambda sev, rule, msg, team, sku=None: findings.append(Finding(sev, rule, msg, team, sku))

    # --- launch level -------------------------------------------------------
    if launch.first_bill_run <= launch.launch_date:
        add("block", "bill-run-before-launch",
            "first bill run must be after launch date", "billing_eng")
    unknown = sorted(set(launch.signoffs) - set(SIGNOFF_TEAMS))
    if unknown:
        add("block", "unknown-signoff-team", f"unknown teams {unknown}", "product")
    missing = [t for t in REQUIRED_SIGNOFFS if t not in launch.signoffs]
    if missing:
        add("block", "missing-required-signoff",
            f"sign-off list must include {missing}", "product")
    for question in launch.open_questions:
        add("block", "open-question", question, "product")

    # --- products -----------------------------------------------------------
    seen: set[str] = set()
    for p in launch.products:
        if p.sku in seen:
            add("block", "duplicate-sku", "SKU appears twice", "pricing", p.sku)
        seen.add(p.sku)
        findings.extend(_lint_product(p, launch))

    # --- bundles ------------------------------------------------------------
    for b in launch.bundles:
        if not b.required:
            add("block", "bundle-no-required", "bundle has no required component", "pricing", b.sku)
        for sku in b.required + b.optional:
            if launch.product(sku) is None:
                add("block", "bundle-unknown-component",
                    f"component {sku} is not in the spec", "pricing", b.sku)

    # --- approvals ----------------------------------------------------------
    caps = [a.max_discount_pct for a in launch.approvals]
    if not caps:
        add("block", "no-approval-matrix", "no discount approval bands", "deal_desk")
    elif caps != sorted(caps) or len(set(caps)) != len(caps):
        add("block", "approval-bands-order",
            "approval bands must have strictly increasing max_discount_pct", "deal_desk")
    elif caps[-1] > 50:
        add("warn", "deep-discount-allowed",
            f"approvals allow up to {caps[-1]}% discount; confirm margin floor", "finance")

    # --- retirements --------------------------------------------------------
    for r in launch.retirements:
        if launch.product(r.replacement) is None:
            add("block", "retire-no-replacement",
                f"replacement {r.replacement} is not in the spec", "product", r.sku)
        if r.end_of_sale > r.end_of_renewal:
            add("block", "retire-dates-order", "end_of_sale is after end_of_renewal", "product", r.sku)
        if r.end_of_sale < launch.launch_date:
            add("warn", "retire-before-launch",
                "old SKU stops selling before its replacement launches; sellers have nothing to quote",
                "product", r.sku)
        if r.policy not in MIGRATION_POLICIES:
            add("block", "retire-unknown-policy", f"policy {r.policy!r}", "finance", r.sku)
    return findings


def _lint_product(p: Product, launch: Launch) -> list[Finding]:
    out: list[Finding] = []
    add = lambda sev, rule, msg, team: out.append(Finding(sev, rule, msg, team, p.sku))

    if p.model not in MODELS:
        add("block", "unknown-model", f"model {p.model!r}; expected one of {MODELS}", "pricing")
        return out
    if not p.tax_code:
        add("block", "missing-tax-code", "no tax code: the tax engine cannot tax invoices", "tax")
    if p.revenue not in REVENUE_TREATMENTS:
        add("block", "missing-revenue-treatment",
            f"revenue treatment {p.revenue!r}; expected one of {REVENUE_TREATMENTS}", "accounting")
    if p.billing_frequency not in BILLING_MONTHS:
        add("block", "billing-frequency",
            f"billing frequency {p.billing_frequency!r}; expected {tuple(BILLING_MONTHS)}", "pricing")
    elif p.term_months % BILLING_MONTHS[p.billing_frequency]:
        add("block", "term-not-billable",
            f"{p.term_months}-month term cannot be billed in whole {p.billing_frequency} periods",
            "pricing")

    if p.model in ("flat", "per_seat"):
        if not p.list_price or p.list_price <= 0:
            add("block", "missing-list-price", "needs a positive list price", "pricing")
        if p.model == "per_seat" and p.min_quantity < 1:
            add("block", "seat-minimum", "minimum seats must be at least 1", "pricing")
        if p.revenue not in (None, "ratable") and p.revenue in REVENUE_TREATMENTS:
            add("warn", "subscription-not-ratable",
                "recurring subscription not recognized ratably; confirm with Accounting", "accounting")

    if p.model == "usage_tiered":
        if not p.unit:
            add("block", "usage-no-unit", "usage product needs a unit of measure", "pricing")
        if not p.usage_source:
            add("block", "usage-no-source",
                "no source of truth for usage quantities; billing cannot invoice it", "billing_eng")
        if p.tier_mode not in TIER_MODES:
            add("block", "tier-mode", f"tier_mode must be one of {TIER_MODES}", "pricing")
        out.extend(_lint_tiers(p))
        if p.billing_frequency not in (None, "monthly"):
            add("warn", "usage-billing-lag",
                "usage billed less often than monthly delays cash and hides overruns", "finance")
        if p.revenue not in (None, "usage") and p.revenue in REVENUE_TREATMENTS:
            add("warn", "usage-revenue",
                "usage product not recognized as consumed; confirm with Accounting", "accounting")

    if p.model == "committed":
        years = [r.year for r in p.ramp]
        if not p.ramp:
            add("block", "commit-no-ramp", "committed product needs at least one ramp year", "pricing")
        elif years != list(range(1, len(years) + 1)):
            add("block", "ramp-years", f"ramp years must be 1..n in order, got {years}", "pricing")
        elif p.term_months != 12 * len(p.ramp):
            add("block", "ramp-term-mismatch",
                f"{p.term_months}-month term but {len(p.ramp)} ramp years; contract and billing disagree",
                "legal")
        if any(r.commit <= 0 for r in p.ramp):
            add("block", "ramp-non-positive", "every ramp year needs a positive commit", "pricing")
        if any(b.commit < a.commit for a, b in zip(p.ramp, p.ramp[1:])):
            add("warn", "down-ramp", "commit decreases in a later year; confirm with Finance", "finance")
        if p.drawdown_rate is None or p.overage_rate is None:
            add("block", "commit-rates", "needs drawdown_rate and overage_rate", "pricing")
        elif p.overage_rate < p.drawdown_rate:
            add("warn", "cheap-overage",
                "overage is cheaper than committed usage; rewards under-committing", "pricing")
        usage = launch.product(p.usage_sku) if p.usage_sku else None
        if usage is None or usage.model != "usage_tiered":
            add("block", "commit-usage-sku",
                f"usage_sku {p.usage_sku!r} must be a usage_tiered product in this spec", "pricing")
        elif usage.tiers and p.overage_rate is not None and p.overage_rate > usage.tiers[0].price:
            add("warn", "overage-above-payg",
                "committed customers pay more for overage than pay-as-you-go list", "sales")
    return out


def _lint_tiers(p: Product) -> list[Finding]:
    out: list[Finding] = []
    add = lambda sev, rule, msg, team: out.append(Finding(sev, rule, msg, team, p.sku))
    if not p.tiers:
        add("block", "no-tiers", "usage product has no price tiers", "pricing")
        return out
    bounds = [t.up_to for t in p.tiers]
    if bounds[-1] is not None:
        add("block", "last-tier-bounded",
            "last tier needs up_to: null, or usage above it cannot be priced", "pricing")
    if any(b is None for b in bounds[:-1]):
        add("block", "unbounded-middle-tier", "only the last tier may be unbounded", "pricing")
    finite = [b for b in bounds if b is not None]
    if finite != sorted(finite) or len(set(finite)) != len(finite) or (finite and finite[0] <= 0):
        add("block", "tier-bounds", "tier upper bounds must be positive and strictly increasing", "pricing")
    prices = [t.price for t in p.tiers]
    if any(b > a for a, b in zip(prices, prices[1:])):
        add("warn", "price-rises-with-volume",
            "a higher tier costs more per unit than a lower one", "pricing")
    if any(price < 0 for price in prices):
        add("block", "negative-price", "tier price below zero", "pricing")
    return out


def blocking(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "block"]
