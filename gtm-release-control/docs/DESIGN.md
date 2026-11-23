# Design: gtm-release-control

Audience: engineers on the GTM Systems team.

## Problem

Changes reach a SOX-scoped Salesforce org by hand: change sets or ad hoc CLI deploys, approvals in
Slack threads, and evidence rebuilt after the fact. That process is slow for low-risk changes and
weak for high-risk ones. Agents can now write a lot of this work, but a pipeline built for humans
has no way to decide what an agent may ship alone.

## Goals

1. One path to production for Salesforce metadata and custom-app code.
2. Every change routed by risk into a lane with explicit gates.
3. Evidence produced by the pipeline as it runs, not reconstructed later.
4. Every automated decision assumed fallible: fail closed, contain blast radius, roll back fast.

Non-goals: data migrations (separate runbook), managed-package upgrades, multi-org fan-out.

## Branching model

Trunk-based. Short-lived branches → PR → squash-merge to `main` → deploy.

- **Why not GitFlow with long-lived `develop`/`uat` branches?** Long-lived Salesforce branches drift
  from the org and from each other. Merge conflicts in profile XML are where outages come from.
  Environments are promotion targets, not branches.
- **Squash + linear history**: one commit per change, so a rollback is one reverse delta and one revert.
- **Strict up-to-date**: the branch must contain the latest `main` before merge, so the
  check-only deploy validated on the PR is the same change that ships.

## Validation

| Step | Why |
|---|---|
| Scratch org per PR | Tests run against a clean org built from source. No shared sandbox state, and no PR breaks another PR's sandbox |
| `RunLocalTests` + 85% org-wide coverage | Salesforce requires 75% to deploy. 85% leaves headroom so one new class can't block a hotfix |
| Code Analyzer (severity ≤ 2 blocks) | Catches SOQL-in-loop, missing sharing, and CRUD/FLS issues before review |
| Production check-only deploy | Proves the delta deploys to the *real* org (its config, its data shape) without changing it. The validated ID is quick-deployed after merge |

**Delta deploys** (`sfdx-git-delta`): deploy only what changed. Full-source deploys to a large
org are slow and widen the blast radius to components nobody touched.

## Lane routing

See [README](../README.md#lanes). Key decisions:

- **Hard rules set a floor, the model can only raise it.** The diff is untrusted input to the
  model. If the model could lower risk, a comment in the diff saying "this is safe" would become
  an attack. With only-raise semantics, the worst a manipulated model can do is ask for more review.
- **Fail closed everywhere.** No key, refusal, `max_tokens`, malformed JSON, or an oversized diff
  all route to `human_in_loop`. The diff is never truncated, because a truncated diff hides
  exactly the part that matters.
- **The pipeline is floored at human_in_loop.** Agents cannot edit the controls that constrain them.
- **Classifier and gate run from the base branch.** A PR cannot change the code that judges it.
- **Escalation is one-way.** Two validation failures bump a PR one lane. Re-pushing never lowers a lane.

## Agent operations

See [agents/README.md](../agents/README.md). In summary: agents get no org credentials, can't edit the
pipeline, and can't merge, review, or relabel. Their PRs go through the same classifier and gate as
a human's. "Agentic" is a lane the pipeline grants, not one the author claims.

## Approvals: two distinct gates

| | PR review | Business sign-off |
|---|---|---|
| Question answered | Is the change built correctly? | Should this change happen to the business? |
| Who | Engineer (CODEOWNERS for security model and pipeline) | Listed business approver (RevOps, Finance) |
| Mechanism | GitHub approving review | `signoff:business` label, actor checked |
| Rules | Not the author. Stale approvals dismissed on push | Not the author, and not the only code reviewer |

`human_in_loop` deploys also wait on the `production-gated` environment for a release approver.
That approval is the change-window control.

## Rollback

Triggered automatically when post-deploy smoke tests fail, or manually via `workflow_dispatch`.

1. Open a `deploy-freeze` issue (kill-switch for every deploy).
2. Build the reverse delta `bad → good` with sfdx-git-delta: redeploy the old versions, destructively
   remove components the bad change added.
3. Deploy with `RunLocalTests`, then write a ledger entry.
4. Open a revert PR so `main` matches production again. Otherwise the next deploy re-ships the bad change.

**Rollback drill (fault injection):** set the repo variable `SMOKE_TEST_CLASSES=DoesNotExist`, then merge a
change. The deploy succeeds, smoke tests fail, and the full rollback path runs. Unset the variable afterward.
No code change is needed to rehearse it.

**What rollback cannot undo**, and how it's handled:

- **Data** written while the bad version was live. This is why revenue-object changes are `human_in_loop`.
  Next step: snapshot affected records before those deploys.
- **Deleted fields** lose their data (recoverable from the recycle bin for 15 days only).
  `destructiveChanges` is floored at `human_in_loop`.
- **Picklist value removals and some Flow version changes** don't reverse cleanly. Review catches these.
- **Integrations** that consumed bad data downstream. Out of scope for metadata rollback; incident process.

## Secrets and environments

| Environment | Holds | Who can trigger |
|---|---|---|
| (none) | Dev Hub JWT | PR validation: scratch orgs only |
| `prod-validate` | Prod JWT for a check-only integration user | PR validation |
| `production` | Prod JWT | Merge to `main`, agentic/ai_assisted |
| `production-gated` | Prod JWT | Merge to `main`, human_in_loop, after a release approver |
| `production-rollback` | Prod JWT | Rollback only |

JWT (connected app + certificate) for every org. No stored passwords or refresh tokens. The key
is written to a temp file and removed at the end of the step. The agent job holds only the Anthropic key.

## Metrics

From the ledger ([`metrics/`](../metrics/)): lead time, change failure rate, lane share, and **policy gaps**.
Policy gaps are paths no rule covers. Each one forced human review of something the policy never
decided about, so each is a candidate for a new rule.

## Setup

For a live demo on a free Developer Edition org, run [`scripts/bootstrap-demo.sh`](../scripts/bootstrap-demo.sh).
It walks through each step below and prompts for your values.

1. Create a Dev Hub and a production connected app (JWT). Store `SF_DEVHUB_*` and `SF_PROD_*` secrets.
2. Create a GitHub App for the classifier. Set `CLASSIFIER_APP_ID`, `CLASSIFIER_APP_KEY`, and `CLASSIFIER_ACTOR`.
3. Add the `ANTHROPIC_API_KEY` secret.
4. Run `terraform apply` in `infra/`, or step 9 of the bootstrap script for a demo repo.
