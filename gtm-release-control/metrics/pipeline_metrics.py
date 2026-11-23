"""Measure the pipeline itself, from the evidence ledger.

- lead time: PR opened → production deploy (median, hours)
- change failure rate: deploys that were rolled back / all deploys
- lane share: deployed PRs per lane
- policy gaps: changed paths no rule covers. Each one forced a human to review
  something the policy never decided about, so it is a candidate for a new rule.
"""
from __future__ import annotations

import argparse
import calendar
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evidence.ledger import read_entries  # noqa: E402


def iso_to_epoch(value: str) -> int:
    return calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ"))


def compute(entries: list[dict]) -> dict:
    deploys = [e for e in entries if e["event"] == "deploy"]
    rolled_back = {e["data"]["bad_sha"] for e in entries if e["event"] == "rollback"}

    lead_hours = [
        (d["ts"] - iso_to_epoch(d["data"]["pr_opened_at"])) / 3600
        for d in deploys
        if d["data"].get("pr_opened_at")
    ]
    lanes = Counter(d["data"].get("lane", "unknown") for d in deploys)
    gaps = Counter(
        reason.split(":", 1)[0]
        for d in deploys
        for reason in d["data"].get("classification_reasons", [])
        if "policy gap" in reason
    )
    total = len(deploys)
    return {
        "deploys": total,
        "lead_time_hours_median": round(statistics.median(lead_hours), 2) if lead_hours else None,
        "change_failure_rate": round(
            sum(1 for d in deploys if d["data"]["sha"] in rolled_back) / total, 3
        ) if total else None,
        "lane_share": {lane: round(n / total, 3) for lane, n in sorted(lanes.items())} if total else {},
        "policy_gaps": dict(gaps.most_common(10)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(compute(read_entries(args.ledger)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
