"""Fail the build unless Apex tests passed and org-wide coverage meets the bar.

Reads the JSON from `sf apex run test --code-coverage --json`.
Salesforce requires 75% to deploy to production; this pipeline holds the line at 85%.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_MIN_COVERAGE = 85.0


def check(result: dict, min_coverage: float) -> list[str]:
    summary = result.get("result", {}).get("summary", {})
    problems = []
    if summary.get("outcome") != "Passed":
        problems.append(
            f"Apex tests outcome={summary.get('outcome')!r} "
            f"(failing={summary.get('failing')}, passing={summary.get('passing')})"
        )
    raw = summary.get("orgWideCoverage")
    if raw is None:
        problems.append("no orgWideCoverage in results; was --code-coverage passed?")
    else:
        coverage = float(str(raw).rstrip("%"))
        if coverage < min_coverage:
            problems.append(f"org-wide coverage {coverage}% is below {min_coverage}%")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("results", type=Path)
    parser.add_argument("--min-coverage", type=float, default=DEFAULT_MIN_COVERAGE)
    args = parser.parse_args()
    with args.results.open("r", encoding="utf-8") as f:
        problems = check(json.load(f), args.min_coverage)
    for problem in problems:
        print(f"::error::{problem}")
    print("coverage gate passed" if not problems else "coverage gate failed")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
