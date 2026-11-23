# Data contracts

Machine-readable versions are in [`contracts/`](../contracts). The Python tests validate every
payload the system builds against them.

## What each system may assume

| Contract | Producer | Consumer | Guarantees | Consumer must |
|---|---|---|---|---|
| `q2c.contract.v1` | Salesforce | Billing | Full snapshot; `version` strictly increases per contract; same key = same bytes | Replay the stored response for a repeated `Idempotency-Key`; 409 when `version` < stored; re-apply when `version` == stored (repair); store a cancelled tombstone if a cancel arrives for an unknown contract |
| `q2c.agreement.v1` | Salesforce | CLM | Keyed by `externalReference` (Salesforce Id) | Upsert by `externalReference`; never create a second agreement for the same reference |
| `q2c.clm-event.v1` | CLM | Salesforce | `eventId` unique per event; `agreementVersion` increases with each agreement change; signed | Nothing; Salesforce dedupes, orders and validates |
| `q2c.billing-contract.v1` | Billing | Salesforce (reconciliation) | Current stored state, same `lineKey`s it was sent | n/a |

## Keys

| Key | Format | Unique where |
|---|---|---|
| Outbound message | `billing:upsert_contract:<contractId>:v<version>` | `Sync_Message__c.Idempotency_Key__c`, and the target's idempotency store |
| Repair | `<outbound key>:repair:<runId>` | Same |
| Inbound event | `clm-in:<eventId>` | `Sync_Message__c.Idempotency_Key__c` |
| Line | `<contractId>:<productCode>` | `Q2C_Subscription__c.Line_Key__c` and Billing's line store; the reconciliation join |

## Response codes the dispatcher understands

| Code | Meaning to us |
|---|---|
| 2xx | Applied (or replayed) |
| 409 | Target holds a newer version: Superseded |
| 408, 425, 429, 5xx, timeout, connection error | Transient: retry with the same key |
| Any other 4xx | Our payload or credentials are wrong: Dead, a person fixes it |

## Changing a contract

- Adding an optional field is backward compatible. Consumers must ignore unknown fields.
- Removing or renaming a field, or changing a type or meaning, is a new `schema` value
  (`q2c.contract.v2`). Both versions are sent in parallel until the consumer confirms the cut-over.
- `vectors/sync-vectors.json` changes go in the same PR as the Apex and Python changes. CI fails if
  the Apex copy and the Python copy differ.
