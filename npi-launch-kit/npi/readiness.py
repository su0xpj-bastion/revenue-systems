"""Launch readiness: checklist items derived from the spec, a launch calendar, and a go/no-go.

Items come from the spec, not from a template someone copies. A usage product adds metering and
tier items; a committed product adds contract and ramp items; a retirement adds migration items.
Nothing applicable can be forgotten, and nothing irrelevant clutters the list.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

from .lint import blocking, lint
from .spec import Launch


@dataclass(frozen=True)
class Item:
    id: str
    workstream: str
    task: str
    owner: str
    due: date


def build_items(launch: Launch) -> list[Item]:
    t = launch.launch_date
    d = lambda days: t + timedelta(days=days)
    items = [
        Item("spec:frozen", "intake", "Pricing & packaging spec frozen; open questions closed", "pricing", d(-45)),
        Item("approvals:rules", "quoting", "Discount approval rules built and tested", "deal_desk", d(-21)),
        Item("quoting:templates", "quoting", "Quote templates show new SKUs, terms and tiers", "deal_desk", d(-14)),
        Item("scenarios:pass", "testing", "Quote + billing scenario suite passes in sandbox", "billing_eng", d(-14)),
        Item("enablement:sellers", "enablement", "Seller and Deal Desk guidance published, session held", "sales", d(-7)),
        Item("launch:activate", "launch", "Products activated in production price book", "product", d(0)),
        Item("post:first-quotes", "post-launch", "First live quotes checked against expected pricing", "deal_desk", d(3)),
        Item("post:reconcile", "post-launch",
             "Quote → order → invoice → finance report reconciliation clean",
             "finance", launch.first_bill_run + timedelta(days=5)),
        Item("post:review", "post-launch", "Post-launch review held; fixes added to playbook", "product", d(45)),
    ]
    for p in launch.products:
        items += [
            Item(f"catalog:{p.sku}", "catalog", f"{p.sku}: Product2 + price book entry loaded in sandbox", "product", d(-30)),
            Item(f"tax:{p.sku}", "tax", f"{p.sku}: tax code {p.tax_code or '???'} mapped in tax engine", "tax", d(-21)),
            Item(f"billing:{p.sku}", "billing", f"{p.sku}: billing plan configured ({p.model})", "billing_eng", d(-21)),
            Item(f"reporting:{p.sku}", "reporting", f"{p.sku}: mapped to finance reporting line", "finance", d(-14)),
        ]
        if p.model == "usage_tiered":
            items += [
                Item(f"metering:{p.sku}", "billing",
                     f"{p.sku}: usage feed from {p.usage_source or '???'} lands in billing", "billing_eng", d(-21)),
                Item(f"tiers:{p.sku}", "catalog", f"{p.sku}: {p.tier_mode} tiers loaded", "product", d(-30)),
            ]
        if p.model == "committed":
            items.append(Item(f"contract:{p.sku}", "contracts",
                              f"{p.sku}: order form language for commit, ramp and overage", "legal", d(-14)))
    for b in launch.bundles:
        items.append(Item(f"bundle:{b.sku}", "catalog", f"{b.sku}: bundle options configured", "product", d(-30)))
    for r in launch.retirements:
        items += [
            Item(f"eos:{r.sku}", "retirement", f"{r.sku}: end-of-sale date set; blocked on new quotes", "product", d(-7)),
            Item(f"migration:{r.sku}", "retirement",
                 f"{r.sku}: migration plan ({r.policy}) approved; renewals on {r.replacement} tested", "finance", d(-14)),
        ]
    return sorted(items, key=lambda i: (i.due, i.workstream, i.id))


def load_tracker(path: Path) -> tuple[set[str], dict[str, dict]]:
    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return set(data.get("done") or []), dict(data.get("signoffs") or {})


def status_of(item: Item, done: set[str], today: date) -> str:
    if item.id in done:
        return "DONE"
    if item.due < today:
        return "OVERDUE"
    if item.due <= today + timedelta(days=7):
        return "DUE SOON"
    return "OPEN"


def go_no_go(launch: Launch, done: set[str], signoffs: dict, today: date) -> tuple[bool, list[str]]:
    reasons = [f"spec: {f}" for f in blocking(lint(launch))]
    for item in build_items(launch):
        if item.due <= launch.launch_date and item.id not in done:
            reasons.append(f"not done: {item.task} (owner {item.owner}, due {item.due})")
    for team in launch.signoffs:
        if team not in signoffs:
            reasons.append(f"missing sign-off: {team}")
    return not reasons, reasons


def report(launch: Launch, done: set[str], signoffs: dict, today: date) -> str:
    items = build_items(launch)
    go, reasons = go_no_go(launch, done, signoffs, today)
    pre = [i for i in items if i.due <= launch.launch_date]
    lines = [
        f"# Launch readiness: {launch.name} ({launch.code})",
        "",
        f"Launch {launch.launch_date} · first bill run {launch.first_bill_run} · as of {today} "
        f"(T{(today - launch.launch_date).days:+d} days)",
        "",
        f"**Decision: {'GO' if go else 'NO-GO'}**: {sum(i.id in done for i in pre)}/{len(pre)} pre-launch "
        f"items done, {sum(t in signoffs for t in launch.signoffs)}/{len(launch.signoffs)} sign-offs.",
        "",
        "## Calendar",
        "",
        "| Due | Status | Workstream | Item | Owner |",
        "|---|---|---|---|---|",
    ]
    for item in items:
        lines.append(f"| {item.due} | {status_of(item, done, today)} | {item.workstream} | {item.task} | {item.owner} |")
    lines += ["", "## Sign-offs", "", "| Team | Signed by | Date |", "|---|---|---|"]
    for team in launch.signoffs:
        s = signoffs.get(team)
        lines.append(f"| {team} | {s['by'] if s else '—'} | {s.get('date', '?') if s else 'pending'} |")
    if reasons:
        lines += ["", "## Blocking", ""] + [f"- {r}" for r in reasons]
    return "\n".join(lines) + "\n"
