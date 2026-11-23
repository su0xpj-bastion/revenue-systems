"""Quote and billing scenario tests.

A scenario is a quote plus monthly usage. The engine computes the invoice schedule and the
approval route; the scenario file holds the expected values a human agreed with Finance.
A mismatch means the pricing rules, the spec, or the expectation is wrong. All three are
worth knowing before launch day.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

from .pricing import QuoteLine, approver_for, invoice_schedule, money
from .spec import Launch, as_date


@dataclass
class Scenario:
    name: str
    start: date
    lines: list[QuoteLine]
    usage: dict[str, list[Decimal]]
    expect_total: Decimal | None = None
    expect_first_invoice: Decimal | None = None
    expect_approver: str | None = None
    expect_error: str | None = None


@dataclass
class Result:
    scenario: Scenario
    passed: bool
    total: Decimal | None = None
    first_invoice: Decimal | None = None
    approver: str | None = None
    error: str | None = None
    problems: list[str] = field(default_factory=list)


def parse_scenarios(data: dict) -> list[Scenario]:
    scenarios = []
    for raw in data.get("scenarios") or []:
        expect = raw.get("expect") or {}
        scenarios.append(Scenario(
            name=raw["name"],
            start=as_date(raw["start"]),
            lines=[
                QuoteLine(l["sku"], Decimal(str(l.get("quantity", 1))), Decimal(str(l.get("discount_pct", 0))))
                for l in raw["lines"]
            ],
            usage={sku: [Decimal(str(u)) for u in months] for sku, months in (raw.get("usage") or {}).items()},
            expect_total=None if expect.get("total") is None else Decimal(str(expect["total"])),
            expect_first_invoice=(
                None if expect.get("first_invoice") is None else Decimal(str(expect["first_invoice"]))
            ),
            expect_approver=expect.get("approver"),
            expect_error=expect.get("error"),
        ))
    return scenarios


def load_scenarios(path: Path) -> list[Scenario]:
    with Path(path).open("r", encoding="utf-8") as f:
        return parse_scenarios(yaml.safe_load(f))


def run(launch: Launch, scenario: Scenario) -> Result:
    approver = approver_for(launch, max((l.discount_pct for l in scenario.lines), default=Decimal(0)))
    try:
        invoices = invoice_schedule(launch, scenario.lines, scenario.start, scenario.usage)
    except ValueError as exc:
        error = str(exc)
        ok = scenario.expect_error is not None and scenario.expect_error in error
        problems = [] if ok else [f"unexpected error: {error}"]
        return Result(scenario, ok, approver=approver, error=error, problems=problems)

    total = money(sum((i.amount for i in invoices), Decimal(0)))
    first_date = min((i.period_start for i in invoices), default=None)
    first = money(sum((i.amount for i in invoices if i.period_start == first_date), Decimal(0)))

    problems = []
    if scenario.expect_error:
        problems.append(f"expected error containing {scenario.expect_error!r}, got none")
    if scenario.expect_total is not None and total != scenario.expect_total:
        problems.append(f"total {total} != expected {scenario.expect_total}")
    if scenario.expect_first_invoice is not None and first != scenario.expect_first_invoice:
        problems.append(f"first invoice {first} != expected {scenario.expect_first_invoice}")
    if scenario.expect_approver is not None and approver != scenario.expect_approver:
        problems.append(f"approver {approver} != expected {scenario.expect_approver}")
    return Result(scenario, not problems, total, first, approver, problems=problems)


def run_all(launch: Launch, scenarios: list[Scenario]) -> list[Result]:
    return [run(launch, s) for s in scenarios]
