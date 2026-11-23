"""Merge gate: is this PR's approval evidence sufficient for its lane?

Runs as the required status check `lane-gate`. PR review and business sign-off are separate gates:
- agentic        CI only. Lane label must have been applied by the classifier bot.
- ai_assisted    + at least one approving review from someone other than the author.
- human_in_loop  + business sign-off label applied by a listed business approver who is neither
                   the author nor the only code approver (separation of duties).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass

LANE_PREFIX = "lane:"
SIGNOFF_LABEL = "signoff:business"
# The classifier labels PRs with a GitHub App token (GITHUB_TOKEN events do not trigger the gate).
DEFAULT_CLASSIFIER_ACTOR = "gtm-release-classifier[bot]"


@dataclass(frozen=True)
class PullRequestEvidence:
    author: str
    lane_labels: list[str]
    lane_label_actor: str | None
    approvers: set[str]
    signoff_actor: str | None


def evaluate(
    evidence: PullRequestEvidence,
    business_approvers: set[str],
    classifier_actor: str = DEFAULT_CLASSIFIER_ACTOR,
) -> tuple[bool, list[str]]:
    problems: list[str] = []

    if len(evidence.lane_labels) != 1:
        return False, [f"expected exactly one lane label, found {evidence.lane_labels or 'none'}"]
    lane = evidence.lane_labels[0].removeprefix(LANE_PREFIX)

    if evidence.lane_label_actor != classifier_actor:
        problems.append(
            f"lane label set by {evidence.lane_label_actor!r}, not the classifier; "
            "re-run the classify workflow"
        )

    reviewers = evidence.approvers - {evidence.author}
    if lane in ("ai_assisted", "human_in_loop") and not reviewers:
        problems.append("needs one approving review from someone other than the author")

    if lane == "human_in_loop":
        signer = evidence.signoff_actor
        if signer is None:
            problems.append(f"needs business sign-off: label {SIGNOFF_LABEL!r}")
        else:
            if signer not in business_approvers:
                problems.append(f"{signer} applied {SIGNOFF_LABEL} but is not a business approver")
            if signer == evidence.author:
                problems.append("author cannot give business sign-off on their own change")
            if not (reviewers - {signer}):
                problems.append("business signer cannot also be the only code reviewer")
    elif lane not in ("agentic", "ai_assisted"):
        problems.append(f"unknown lane {lane!r}")

    return not problems, problems


def latest_approvers(reviews: list[dict]) -> set[str]:
    """A reviewer counts only if their most recent decisive review is APPROVED."""
    latest: dict[str, str] = {}
    for review in reviews:
        state = review["state"]
        if state in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[review["author"]["login"]] = state
    return {login for login, state in latest.items() if state == "APPROVED"}


def last_label_actor(events: list[dict], predicate) -> str | None:
    """Actor of the most recent `labeled` event whose label is still meaningful."""
    actor = None
    for event in events:
        if event.get("event") == "labeled" and predicate(event["label"]["name"]):
            actor = event["actor"]["login"]
        elif event.get("event") == "unlabeled" and predicate(event["label"]["name"]):
            actor = None
    return actor


def gh_json(*args: str):
    out = subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def fetch_evidence(repo: str, number: int) -> PullRequestEvidence:
    pr = gh_json("pr", "view", str(number), "--repo", repo, "--json", "author,labels,reviews")
    events = gh_json("api", "--paginate", "--slurp", f"repos/{repo}/issues/{number}/events")
    flat_events = [e for page in events for e in page]
    labels = [label["name"] for label in pr["labels"]]
    return PullRequestEvidence(
        author=pr["author"]["login"],
        lane_labels=[name for name in labels if name.startswith(LANE_PREFIX)],
        lane_label_actor=last_label_actor(flat_events, lambda n: n.startswith(LANE_PREFIX)),
        approvers=latest_approvers(pr["reviews"]),
        signoff_actor=(
            last_label_actor(flat_events, lambda n: n == SIGNOFF_LABEL)
            if SIGNOFF_LABEL in labels else None
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Check lane approval evidence for a PR")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--output", default="gate.json")
    args = parser.parse_args()

    approvers = {
        login.strip() for login in os.environ.get("BUSINESS_APPROVERS", "").split(",") if login.strip()
    }
    evidence = fetch_evidence(args.repo, args.pr)
    ok, problems = evaluate(
        evidence,
        approvers,
        os.environ.get("CLASSIFIER_ACTOR") or DEFAULT_CLASSIFIER_ACTOR,
    )

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({
            "ok": ok,
            "problems": problems,
            "author": evidence.author,
            "lane_labels": evidence.lane_labels,
            "approvers": sorted(evidence.approvers),
            "signoff_actor": evidence.signoff_actor,
        }, f, indent=2)

    for problem in problems:
        print(f"::error::{problem}")
    print("gate passed" if ok else "gate blocked")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
