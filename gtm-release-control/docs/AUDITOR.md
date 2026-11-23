# Change-management controls: auditor view

Audience: internal audit and external SOX auditors. This document maps each change-management
control objective to how the pipeline enforces it and the evidence it produces.

Scope: changes to the production Salesforce org's metadata and to in-scope internal applications.

## Control matrix

| # | Control objective | How it's enforced | Evidence | Where |
|---|---|---|---|---|
| CM-1 | All production changes are authorized | Only merges to `main` deploy. Direct pushes are blocked by branch protection, including for admins. A deploy with no PR fails | PR record, merge actor, deploy run | Ledger `deploy` entry: `pr`, `pr_url`, `merged_by`, `run_url` |
| CM-2 | Changes are tested before production | Required checks: Apex tests in an isolated org (≥85% coverage), static analysis, check-only deploy against production | Test results, coverage, analyzer report, validation ID | Artifacts `apex-results`, `code-analyzer`, `validated-deploy` |
| CM-3 | Changes are reviewed by someone other than the author | `lane-gate` requires a non-author approval for ai_assisted and human_in_loop. Approvals are dismissed on new commits. The last push must be approved | Review history, gate decision | Artifact `gate-*`, ledger `approvers` |
| CM-4 | Business-impacting changes have business approval | Risk classification routes security-model, revenue, and destructive changes to human_in_loop, which requires sign-off from a listed business approver | Sign-off actor, approver list (version-controlled) | Gate output `signoff_actor`. `BUSINESS_APPROVERS` is managed in `infra/` |
| CM-5 | Segregation of duties | Author can't approve or sign off. Business signer can't be the only code reviewer. Production environment reviewers can't self-approve | Gate decision with reasons | Artifact `gate-*` |
| CM-6 | Production deploys are scheduled/approved for high-risk changes | human_in_loop deploys wait on the `production-gated` environment for a release approver | GitHub deployment approval record | Environment deployment history |
| CM-7 | Failed changes are reversed and recorded | Automatic rollback on smoke-test failure. A freeze issue blocks further deploys until closed | Rollback deploy ID, freeze issue, revert PR | Ledger `rollback` entry |
| CM-8 | Change records are complete and tamper-evident | Hash-chained ledger on a branch with force-push and deletion disabled. Each append verifies the chain first | Ledger file, `verify` output, head hash in each run summary | `evidence-ledger` branch |
| CM-9 | Automated (AI) decisions are bounded | The AI classifier can only raise review requirements, never remove them. On any failure it defaults to the strictest lane. Agents hold no production credentials | Classification record: policy floor, AI lane, rationale | Artifact `classification`, ledger `classification_reasons` |
| CM-10 | Control configuration is itself change-controlled | Branch protection, environments, and approver lists are Terraform in this repo. Any change to them is floored at human_in_loop | PRs to `infra/`, `classifier/`, `gate/` | Git history + ledger |

## How to sample a change

1. Pick an entry from `ledger.jsonl` on the `evidence-ledger` branch.
2. Run `python evidence/ledger.py verify --ledger ledger.jsonl`. It should report `status=OK`, and
   the head hash should match the value printed in the most recent deploy run summary.
3. Open `pr_url`: confirm the reviews, labels, and author match the entry.
4. Open `run_url`: download `evidence-pack-<sha>`, which holds the classification, gate decision, PR snapshot, and deploy and smoke results.
5. In Salesforce Setup → Deployment Status, match `deploy_id`.

## Known limitations (disclosed)

- Artifact retention is 90 days. The ledger is permanent, but evidence packs older than 90 days need
  export to long-term storage (planned: object-locked bucket).
- Tamper evidence depends on an independent copy of the head hash. Until the WORM mirror is in
  place, the run summaries in GitHub Actions serve as that copy.
- Changes made directly in production Setup bypass this pipeline. Detecting them requires a
  scheduled org-to-repo drift check (planned) and Setup Audit Trail review.
