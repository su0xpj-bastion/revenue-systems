"""SOX-style controls over the meter-to-revenue path, run per period, with an evidence pack.

Each control states its objective, whether it prevents or detects, and returns the exceptions
it found. An empty exception list is the evidence the control operated and passed.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path

import yaml

from .billing import digest
from .model import Book, period_bounds
from .rating import rerate_independently
from .revenue import AR, DEFERRED, journal, roll_forward, trial_balance
from .store import Store


@dataclass
class ControlResult:
    id: str
    name: str
    objective: str
    nature: str            # preventive | detective
    exceptions: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.exceptions


def c01_usage_completeness(store: Store, **_) -> ControlResult:
    r = ControlResult("C-01", "Usage batch completeness",
                      "Every usage batch received matches the producer's manifest count and quantity",
                      "detective")
    for b in store.batches():
        if b["manifest_count"] != b["received_count"] or Decimal(b["manifest_quantity"]) != Decimal(b["received_quantity"]):
            r.exceptions.append(
                f"{b['batch_id']}: manifest {b['manifest_count']} events / {b['manifest_quantity']} units, "
                f"received {b['received_count']} / {b['received_quantity']}")
        if b["rejected"]:
            r.exceptions.append(f"{b['batch_id']}: {b['rejected']} events rejected by validation")
    r.evidence = {"batches": [dict(b) for b in store.batches()]}
    return r


def c02_usage_billed(store: Store, period: str, **_) -> ControlResult:
    r = ControlResult("C-02", "Usage billed exactly once",
                      "Every accepted event up to period end is on exactly one invoice; duplicates never billed",
                      "preventive")
    _, end = period_bounds(period)
    unbilled = [e["event_id"] for e in store.all_events() if e["ts"] < end.isoformat() and not e["billed_invoice_id"]]
    if unbilled:
        r.exceptions.append(f"{len(unbilled)} events before {end} not billed: {unbilled[:5]}")
    r.evidence = {"duplicates_rejected": sum(b["duplicates"] for b in store.batches()),
                  "events_billed": sum(1 for e in store.all_events() if e["billed_invoice_id"])}
    return r


def c03_rating_accuracy(store: Store, book: Book, period: str, **_) -> ControlResult:
    r = ControlResult("C-03", "Rating accuracy (independent re-rate)",
                      "Usage line amounts equal an independent re-rating of the events billed on them",
                      "detective")
    checked = 0
    for inv in store.invoices():
        if inv["period"] != period:
            continue
        events = store.events_for_invoice(inv["invoice_id"])
        for line in inv["lines"]:
            if line["kind"] != "usage":
                continue
            product = book.products[line["product"]]
            quantity = sum((Decimal(e["quantity"]) for e in events if e["meter"] == product.meter), Decimal(0))
            expected = rerate_independently(product, quantity).quantize(Decimal("0.01"))
            checked += 1
            if Decimal(line["quantity"]) != quantity or Decimal(line["amount"]) != expected:
                r.exceptions.append(f"{inv['invoice_id']} {product.code}: billed {line['quantity']} → "
                                    f"{line['amount']}, re-rated {quantity} → {expected}")
    r.evidence = {"usage_lines_checked": checked}
    return r


def c04_invoice_immutability(store: Store, **_) -> ControlResult:
    r = ControlResult("C-04", "Finalized invoices unchanged",
                      "Every finalized invoice still matches the hash recorded at finalization",
                      "detective")
    rows = store.invoice_rows()
    for row in rows:
        if digest(json.loads(row["body"])) != row["sha256"]:
            r.exceptions.append(f"{row['invoice_id']}: content does not match finalization hash")
    r.evidence = {"invoices_checked": len(rows)}
    return r


def c05_tax_determination(store: Store, book: Book, period: str, **_) -> ControlResult:
    r = ControlResult("C-05", "Tax determined on every line",
                      "Each invoice line has a tax code and a tax engine result; exemptions cite a certificate",
                      "detective")
    for inv in store.invoices():
        if inv["period"] != period:
            continue
        customer = book.customers[inv["customer_id"]]
        for line in inv["lines"]:
            if not line["tax_code"] or not line["tax_note"]:
                r.exceptions.append(f"{inv['invoice_id']} {line['product']}: no tax determination")
            if Decimal(line["tax"]) == 0 and Decimal(line["amount"]) != 0 and not customer.exemption_certificate \
                    and book.tax_rates.get(customer.jurisdiction, {}).get(line["tax_code"], Decimal(0)) != 0:
                r.exceptions.append(f"{inv['invoice_id']} {line['product']}: zero tax on a taxable line")
    return r


def c06_deferred_rollforward(store: Store, book: Book, period: str, **_) -> ControlResult:
    r = ControlResult("C-06", "Deferred revenue roll-forward ties to GL",
                      "Beginning + billed − released = ending, and ending equals the GL deferred balance",
                      "detective")
    invoices = store.invoices(through_period=period)
    rf = roll_forward(book, invoices, period)
    gl = trial_balance(journal(book, invoices, period), period)
    schedule_end = rf[-1].ending if rf else Decimal(0)
    gl_deferred = -gl.get(DEFERRED, Decimal(0))     # credit balance
    if schedule_end != gl_deferred:
        r.exceptions.append(f"schedule ending {schedule_end} != GL deferred {gl_deferred}")
    r.evidence = {"rollforward": [
        {"period": x.period, "beginning": str(x.beginning), "billed": str(x.billed),
         "released": str(x.released), "ending": str(x.ending)} for x in rf]}
    return r


def c07_ar_subledger(store: Store, book: Book, period: str, **_) -> ControlResult:
    r = ControlResult("C-07", "Billing subledger ties to GL; entries balance",
                      "Invoice totals for the period equal AR debits; every journal entry balances",
                      "detective")
    invoices = store.invoices(through_period=period)
    entries = journal(book, invoices, period)
    unbalanced = [e.reference for e in entries if not e.balanced]
    if unbalanced:
        r.exceptions.append(f"unbalanced entries: {unbalanced}")
    billed = sum((Decimal(i["total"]) for i in invoices if i["period"] == period), Decimal(0))
    gl_ar = trial_balance(entries, period, period).get(AR, Decimal(0))
    if billed != gl_ar:
        r.exceptions.append(f"invoices {billed} != GL AR {gl_ar}")
    r.evidence = {"invoice_total": str(billed), "gl_ar": str(gl_ar), "entries": len(entries)}
    return r


def c08_price_change_sod(changes_path: Path | None, period: str, **_) -> ControlResult:
    r = ControlResult("C-08", "Price changes approved by someone else",
                      "Every contract price or quantity change has an approver who is not the requester",
                      "detective")  # the preventive version is the CPQ approval process itself
    changes = []
    if changes_path and Path(changes_path).exists():
        with Path(changes_path).open("r", encoding="utf-8") as f:
            changes = (yaml.safe_load(f) or {}).get("changes") or []
    for c in changes:
        if str(c.get("effective", ""))[:7] > period:
            continue
        if not c.get("approved_by"):
            r.exceptions.append(f"{c['contract']} {c['field']}: no approver")
        elif c["approved_by"] == c["requested_by"]:
            r.exceptions.append(f"{c['contract']} {c['field']}: approved by its own requester {c['requested_by']}")
    r.evidence = {"changes_reviewed": len(changes)}
    return r


CONTROLS = [c01_usage_completeness, c02_usage_billed, c03_rating_accuracy, c04_invoice_immutability,
            c05_tax_determination, c06_deferred_rollforward, c07_ar_subledger, c08_price_change_sod]


def run_controls(store: Store, book: Book, period: str, changes_path: Path | None = None) -> list[ControlResult]:
    return [c(store=store, book=book, period=period, changes_path=changes_path) for c in CONTROLS]


def evidence_pack(results: list[ControlResult], period: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    body = {
        "period": period,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "controls": [asdict(r) | {"passed": r.passed} for r in results],
    }
    raw = json.dumps(body, indent=2, default=str)
    (out_dir / "evidence.json").write_text(raw, encoding="utf-8")
    (out_dir / "evidence.sha256").write_text(hashlib.sha256(raw.encode()).hexdigest() + "\n", encoding="utf-8")

    md = [f"# Control evidence: {period}", "",
          f"{sum(r.passed for r in results)}/{len(results)} controls passed.", "",
          "| ID | Control | Nature | Result |", "|---|---|---|---|"]
    md += [f"| {r.id} | {r.name} | {r.nature} | {'PASS' if r.passed else f'FAIL ({len(r.exceptions)})'} |"
           for r in results]
    for r in results:
        if r.exceptions:
            md += ["", f"## {r.id} exceptions", ""] + [f"- {e}" for e in r.exceptions]
    (out_dir / "evidence.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return out_dir
