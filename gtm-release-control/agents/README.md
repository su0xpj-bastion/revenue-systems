# Agent operations

What agents may do in this pipeline, what they hold, and what they are never trusted to do alone.

## Scope by surface

| | Salesforce work | Custom-app work |
|---|---|---|
| Where the agent runs | GitHub-hosted runner, `agent-task.yml` | Same |
| Org access | **None.** No Salesforce credentials in the job. Validation happens later in a scratch org created by CI, not by the agent | n/a |
| Can edit | `force-app/**` except security model + destructive manifests | `apps/**`, `tests/**`, `docs/**` |
| Can never edit | `profiles`, `permissionsets`, `sharingRules`, `destructiveChanges*.xml` | — |
| Both | `.github/`, `classifier/`, `gate/`, `evidence/`, `agents/`, `infra/`, `CODEOWNERS`: the agent cannot change the controls that constrain it | |
| Can run | `git` on `agent/*` branches, `gh issue view/comment`, `gh pr create`, `pytest` | Same |
| Can never run | `sf`/`sfdx`, `gh pr merge`, `gh pr review`, label edits, workflow dispatch, secrets/variables, network fetches | Same |

Permissions live in [`claude-settings.agent-lane.json`](claude-settings.agent-lane.json) and load from the
default branch, so a PR cannot widen its own agent's permissions.

## Defense in depth

The settings file is the first layer, not the only one. If the agent somehow edits a guardrail file:

1. **Classifier**: `pipeline-guardrails` rule floors the PR at `human_in_loop`.
2. **CODEOWNERS**: guardrail paths need a platform-owner review.
3. **Gate**: the lane label must come from the classifier app, so the agent cannot relabel itself.
4. **Deploy**: production credentials exist only in GitHub environments the agent job never enters.

## What the agent lane is for

Good fits: label and layout changes, report and dashboard metadata, docs, test-only changes, small
Apex fixes with clear tests (these land in `ai_assisted` and get a human review).

Not agent work, ever unsupervised: security model, pricing and CPQ rules, revenue-object automation,
integrations and named credentials, data deletion, and the pipeline itself.

## Kill-switch

Set repository variable `AGENT_LANE_ENABLED=false`:
- `agent-task.yml` stops starting agents.
- The classifier stops granting `agentic`; those PRs route to `ai_assisted` instead.
