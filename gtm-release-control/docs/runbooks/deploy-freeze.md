# Runbook: deploy freeze

A `deploy-freeze` issue is open. Every production deploy fails its kill-switch check until it closes.

## Why it opened

- **Automatic:** `rollback.yml` opens it when post-deploy smoke tests fail.
- **Manual:** anyone on the team can open an issue with the `deploy-freeze` label to stop deploys.

## Before closing it

1. Confirm production matches the last known-good commit (Setup → Deployment Status shows the rollback deploy).
2. Merge the revert PR so `main` matches production.
3. Write down what failed and which guardrail would have caught it earlier.
4. If data was written while the bad version was live, list the affected records and the owner fixing them.

## Close

Close the issue with a link to the revert PR. The next merge to `main` deploys normally.
