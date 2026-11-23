# Where Salesforce DevOps tools stop and custom work begins

Gearset, Copado, and plain sfdx pipelines all solve the *deploy* problem well. This repo uses plain
`sf` CLI + sfdx-git-delta, so every control is visible in code. A team already on Gearset or Copado
can keep it for deploy mechanics and layer the custom parts on top.

| Capability | sf CLI + sfdx-git-delta | Gearset / Copado | Custom here |
|---|---|---|---|
| Delta packaging, destructive changes | ✅ sgd | ✅ built in | — |
| Check-only validation, quick deploy | ✅ | ✅ | — |
| Org comparison / drift detection | partial (`sf project retrieve`) | ✅ strong | — |
| Data deploys / seeding | ❌ | ✅ (Gearset data, Copado data) | — |
| Rollback | manual reverse delta | ✅ snapshot-based | reverse-delta workflow + freeze + revert PR |
| Risk-based routing (agentic / assisted / human) | ❌ | ❌ | ✅ classifier + policy |
| Bounded AI decisions (only-raise, fail-closed) | ❌ | ❌ | ✅ |
| Agent sandboxing (no creds, tool allowlist) | ❌ | ❌ | ✅ agents/ |
| Separation of duties beyond "N approvals" | ❌ | partial (Copado user stories) | ✅ gate: author ≠ signer ≠ sole reviewer |
| Tamper-evident change ledger | ❌ | audit logs (vendor-held) | ✅ hash chain, repo-held |
| Custom-app code in the same pipeline | ✅ (it's just CI) | ❌ Salesforce-only | ✅ |

**Rule of thumb:** buy deploy mechanics and org comparison. Build the parts that encode *your*
risk policy and *your* audit evidence, because no vendor knows which of your objects carry revenue.
