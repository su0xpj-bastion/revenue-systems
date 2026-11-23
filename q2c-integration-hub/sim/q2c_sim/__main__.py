"""python -m q2c_sim [seeds]: run chaos scenarios and print what the design absorbed."""
from __future__ import annotations

import sys
from collections import Counter

from .chaos import run
from .rules import expected_billing_status


def main() -> int:
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    totals: Counter[str] = Counter()
    for seed in range(seeds):
        r = run(seed)
        totals["contracts"] += len(r.sf.contracts)
        totals["billable contracts"] += sum(1 for c in r.sf.contracts.values() if expected_billing_status(c.status))
        totals["requests sent"] += len(r.transport.sent)
        totals["retried sends (same key)"] += len(r.transport.sent) - len(set(r.transport.sent))
        totals["superseded messages"] += sum(1 for m in r.sf.outbox.values() if m.status == "Superseded")
        totals["dead before operator retry"] += r.dead_before_operator
        totals["illegal transitions rejected"] += r.illegal_rejected
        for k, v in r.inbound_outcomes.items():
            totals[f"webhook {k}"] += v
        totals["double applies in Billing"] += sum(1 for n in r.billing.effective_applies.values() if n > 1)
        unsynced = [c for c in r.sf.contracts.values()
                    if expected_billing_status(c.status) and r.billing.get(c.id) is None]
        totals["billable contracts missing in Billing"] += len(unsynced)
        totals["reconciliation drifts after drain"] += len(r.sf.reconcile(r.billing, f"final-{seed}", repair=False))
    width = max(map(len, totals))
    print(f"{seeds} seeded scenarios")
    for k, v in totals.items():
        print(f"  {k:<{width}}  {v}")
    bad = totals["double applies in Billing"] + totals["billable contracts missing in Billing"] + totals["reconciliation drifts after drain"]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
