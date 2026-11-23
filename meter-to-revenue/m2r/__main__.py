"""m2r: meter-to-revenue.

  python -m m2r ingest   BOOK BATCH_DIR          --db FILE
  python -m m2r bill     BOOK PERIOD             --db FILE [--out DIR]
  python -m m2r revenue  BOOK PERIOD             --db FILE
  python -m m2r controls BOOK PERIOD             --db FILE [--changes FILE] --out DIR
  python -m m2r demo     BOOK                    --out DIR      (runs the example end to end)
  python -m m2r stripe-sync   BOOK --ids FILE                   (STRIPE_API_KEY=sk_test_...)
  python -m m2r stripe-parity BOOK --ids FILE --db FILE --start ISO --end ISO [--push]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import controls as ctl
from .billing import BillingError, run_billing
from .ingest import ingest_batch
from .model import BookError, load_book
from .revenue import journal, roll_forward, schedules, trial_balance
from .store import Store
from .tax import RateTableProvider, TaxError


def print_invoices(invoices: list[dict]) -> None:
    for inv in invoices:
        print(f"{inv['invoice_id']}: subtotal {inv['subtotal']} + tax {inv['tax']} = {inv['total']}")
        for l in inv["lines"]:
            print(f"    {l['kind']:15} {l['amount']:>10}  tax {l['tax']:>8}  {l['description']}")


def cmd_ingest(a) -> int:
    book, store = load_book(a.book), Store(a.db)
    r = ingest_batch(store, book, a.batch_dir)
    print(f"{r.batch_id}: accepted {r.accepted}, duplicates {r.duplicates}, late {r.late}, "
          f"rejected {len(r.rejected)}; manifest {r.manifest_count}/{r.manifest_quantity} "
          f"vs received {r.received_count}/{r.received_quantity} → {'complete' if r.complete else 'INCOMPLETE'}")
    for problem in r.rejected:
        print(f"    rejected {problem}")
    return 0


def cmd_bill(a) -> int:
    book, store = load_book(a.book), Store(a.db)
    invoices = run_billing(book, store, a.period, RateTableProvider(book.tax_rates))
    print_invoices(invoices)
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        for inv in invoices:
            (a.out / f"{inv['invoice_id']}.json").write_text(json.dumps(inv, indent=2), encoding="utf-8")
    return 0


def cmd_revenue(a) -> int:
    book, store = load_book(a.book), Store(a.db)
    invoices = store.invoices(through_period=a.period)
    print("Revenue by period")
    for period, r in schedules(book, invoices, a.period).items():
        print(f"  {period}: usage {r.usage} + subscription {r.subscription} + breakage {r.breakage} = {r.revenue}")
    print("Deferred revenue roll-forward")
    for x in roll_forward(book, invoices, a.period):
        print(f"  {x.period}: {x.beginning} + {x.billed} − {x.released} = {x.ending}")
    print(f"Trial balance through {a.period} (debit +, credit −)")
    for account, balance in sorted(trial_balance(journal(book, invoices, a.period), a.period).items()):
        print(f"  {account:20} {balance:>12}")
    return 0


def cmd_controls(a) -> int:
    book, store = load_book(a.book), Store(a.db)
    results = ctl.run_controls(store, book, a.period, a.changes)
    out = ctl.evidence_pack(results, a.period, a.out)
    for r in results:
        print(f"{r.id} {'PASS' if r.passed else 'FAIL'}  {r.name}")
        for e in r.exceptions:
            print(f"       {e}")
    print(f"evidence: {out}")
    return 0 if all(r.passed for r in results) else 1


def cmd_demo(a) -> int:
    book, store = load_book(a.book), Store(":memory:")
    tax = RateTableProvider(book.tax_rates)
    failed = 0
    for period in ("2027-03", "2027-04"):
        print(f"\n===== {period} =====")
        r = ingest_batch(store, book, Path(a.book) / "usage" / f"batch-{period}")
        print(f"ingest {r.batch_id}: accepted {r.accepted}, duplicates {r.duplicates}, late {r.late}, "
              f"{'complete' if r.complete else 'INCOMPLETE'}")
        print_invoices(run_billing(book, store, period, tax))
        results = ctl.run_controls(store, book, period, Path(a.book) / "changes.yaml")
        ctl.evidence_pack(results, period, a.out / period)
        print("controls: " + ", ".join(f"{x.id} {'PASS' if x.passed else 'FAIL'}" for x in results))
        failed += sum(not x.passed for x in results)
    print()
    invoices = store.invoices()
    for x in roll_forward(book, invoices, "2027-04"):
        print(f"deferred {x.period}: {x.beginning} + {x.billed} − {x.released} = {x.ending}")
    print(f"\nevidence packs in {a.out}; {failed} control failures (expected: 2, both planted in April)")
    return 0


def _stripe():
    import stripe
    from .stripe_shadow import require_test_key
    stripe.api_key = require_test_key(os.environ.get("STRIPE_API_KEY"))
    return stripe


def cmd_stripe_sync(a) -> int:
    from .stripe_shadow import catalog_parity, sync_catalog
    stripe, book = _stripe(), load_book(a.book)
    ids = sync_catalog(stripe, book)
    a.ids.write_text(json.dumps(ids, indent=2), encoding="utf-8")
    problems = catalog_parity(stripe, book, ids)
    print("\n".join(problems) or "catalog parity: Stripe prices match the book")
    return 1 if problems else 0


def cmd_stripe_parity(a) -> int:
    from .stripe_shadow import push_usage, usage_parity
    stripe, book, store = _stripe(), load_book(a.book), Store(a.db)
    ids = json.loads(a.ids.read_text(encoding="utf-8"))
    if a.push:
        print(f"pushed {push_usage(stripe, book, store, ids, a.start, a.end)} meter events")
    problems = usage_parity(stripe, book, store, ids, a.start, a.end)
    print("\n".join(problems) or "usage parity: Stripe meter totals match ingested usage")
    return 1 if problems else 0


def main() -> int:
    p = argparse.ArgumentParser(prog="m2r", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ingest"); s.add_argument("book", type=Path); s.add_argument("batch_dir", type=Path)
    s.add_argument("--db", required=True); s.set_defaults(func=cmd_ingest)
    s = sub.add_parser("bill"); s.add_argument("book", type=Path); s.add_argument("period")
    s.add_argument("--db", required=True); s.add_argument("--out", type=Path); s.set_defaults(func=cmd_bill)
    s = sub.add_parser("revenue"); s.add_argument("book", type=Path); s.add_argument("period")
    s.add_argument("--db", required=True); s.set_defaults(func=cmd_revenue)
    s = sub.add_parser("controls"); s.add_argument("book", type=Path); s.add_argument("period")
    s.add_argument("--db", required=True); s.add_argument("--changes", type=Path)
    s.add_argument("--out", type=Path, required=True); s.set_defaults(func=cmd_controls)
    s = sub.add_parser("demo"); s.add_argument("book", type=Path); s.add_argument("--out", type=Path, required=True)
    s.set_defaults(func=cmd_demo)
    s = sub.add_parser("stripe-sync"); s.add_argument("book", type=Path); s.add_argument("--ids", type=Path, required=True)
    s.set_defaults(func=cmd_stripe_sync)
    s = sub.add_parser("stripe-parity"); s.add_argument("book", type=Path); s.add_argument("--ids", type=Path, required=True)
    s.add_argument("--db", required=True); s.add_argument("--start", required=True); s.add_argument("--end", required=True)
    s.add_argument("--push", action="store_true"); s.set_defaults(func=cmd_stripe_parity)
    a = p.parse_args()
    try:
        return a.func(a)
    except (BookError, BillingError, TaxError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
