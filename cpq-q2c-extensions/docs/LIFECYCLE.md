# Quote, order, amendment and renewal lifecycle

## New business

```mermaid
sequenceDiagram
    actor Rep
    participant QLE as Quote line editor
    participant QCP as QCP (calculator)
    participant Q as SBQQ__Quote__c trigger
    participant AA as Advanced Approvals
    Rep->>QLE: add products, discount
    QLE->>QCP: calculate
    QCP-->>QLE: floors, Approval_Level__c, reasons
    Rep->>Q: Submit (QuoteApprovalService)
    alt level 0
        Q->>Q: Draft → Approved
    else level ≥ 1
        Q->>AA: SBAA.ApprovalAPI.submit
        AA-->>Q: In Review → Approved / Denied
    end
    Rep->>Q: Presented → Accepted
    Q->>Q: SBQQ__Ordered__c = true → CPQ creates Order
    Note over Q: Order activated + Contracted → Contract + Subscriptions
```

If an Approved or Presented quote is recalculated and its approval level goes **up**, the trigger
returns it to Draft. Re-pricing can't keep an approval that was given for a smaller ask.

## Advanced Approvals rules (configuration)

| Rule | Condition | Approver | Chain |
|---|---|---|---|
| Deal Desk | `Approval_Level__c >= 1` | Deal Desk queue | 1 |
| Finance | `Approval_Level__c >= 2` | Finance approver | 2 |
| CFO | `Approval_Level__c >= 3` | CFO | 3 |
| Legal | `Legal_Review_Required__c = true` | Legal queue | parallel to the chain |

One numeric field drives the rules, so routing logic lives in code (tested), and the rules stay trivial.

## Amendment (mid-term change)

```mermaid
sequenceDiagram
    participant F as Flow (rep)
    participant S as ContractAmendmentService
    participant P as AmendmentPolicy
    participant CPQ as CPQ API
    F->>S: contract, product, new quantity, effective date
    S->>P: current subscriptions vs request
    P-->>S: OK / violations (decrease, out of term, not on contract)
    S->>CPQ: ContractAmender.load(contractId)
    CPQ-->>S: amendment QuoteModel (existing lines)
    S->>CPQ: set quantities + start date → QuoteSaver
    S->>CPQ: QuoteCalculator (async) → CpqSaveCallback saves
    Note over CPQ: CPQ computes the co-termed delta and proration
```

## Renewal

```mermaid
sequenceDiagram
    participant F as Flow / scheduled job
    participant S as ContractRenewalService
    participant CPQ as CPQ API
    participant QCP as QCP
    F->>S: contract
    S->>CPQ: ContractRenewer.load(masterContractId, context)
    CPQ-->>S: renewal QuoteModel(s)
    S->>S: Prior_Net_Price__c, Grandfathered__c per line; Renewal_Cap_Pct__c from Account
    S->>CPQ: QuoteSaver, then QuoteCalculator
    CPQ->>QCP: onBeforeCalculate
    QCP-->>CPQ: special price = min(list, prior × (1+cap)), or prior if grandfathered
```

## Contract lifecycle

```mermaid
stateDiagram-v2
    [*] --> Draft
    Draft --> InNegotiation: redlines start
    InNegotiation --> Draft: back to drafting
    InNegotiation --> Signed: both parties sign (signed date stamped)
    Signed --> Active: start date reached / order activated
    Active --> Expiring: renewal window opens (job)
    Active --> Terminated: early termination (reason required)
    Expiring --> Renewed: renewal contracted
    Expiring --> Expired: end date passed, no renewal (job)
    Expiring --> Terminated
    Renewed --> [*]
    Expired --> [*]
    Terminated --> [*]
```

`Lifecycle_Status__c` is separate from the standard Contract `Status` because `Activated` carries
platform semantics (activation locks fields and drives CPQ). The trigger enforces the transitions above.

## Renewal notices (nightly `RenewalNoticeJob`)

| As of | Auto-renew | Renewal quote exists | Action |
|---|---|---|---|
| Before notice date − 30 days | any | any | nothing |
| Window open, on/before end date | yes | no | Create the renewal quote (ContractRenewer + capped uplift); contract → Expiring |
| Window open, on/before end date | no | no | One high-priority task for the owner, due on the notice date; contract → Expiring |
| Window open | any | yes | Nothing; the renewal quote is in progress |
| After end date | no | — | Expired |
| After end date | yes | no | Create the renewal quote late (flagged by running after end date) |

Notice date = `EndDate − Notice_Days__c` (default 60). The job is idempotent: a renewal quote is created
once (`Renewal_Quote_Created__c`), and an owner task isn't repeated while one is open.
