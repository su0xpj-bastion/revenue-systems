# Configuration vs code

Default to configuration. Write code only when configuration can't express the rule, can't be
tested, or would have to be repeated in several places. Each piece of code here exists for one of
those reasons.

| Need | Why not configuration alone | Where it lives |
|---|---|---|
| Renewal price = min(list, prior × (1 + account cap)), grandfather override | A per-line min() against a value from the *renewed subscription* and an *account* field, across bundles, needs several price rules plus lookup objects and still can't express min() cleanly | QCP `onBeforeCalculate` |
| Floor price after every discount layer | Price rules run at fixed stages; a floor check has to see the final net price | QCP `onAfterCalculate` |
| One approval level from many signals | Advanced Approvals conditions per signal multiply (discount band × floor × terms × term length). One computed level keeps the rules trivial and puts the logic under test | QCP + `Pricing.approvalLevel` |
| Status can't skip approval | Validation rules see one record. They can't tell a calculation update from a status edit, or apply "re-price up → back to Draft" | `QuoteTriggerHandler` |
| Amend / renew from a screen flow with policy | ContractAmender / ContractRenewer are API calls; the policy (no mid-term decreases) must run before CPQ builds the quote | Apex services + `AmendmentPolicy` |
| Lock discount on grandfathered lines | Field-level security is per user, not per line | QCP `isFieldEditable` |
| Legal review from contract terms | The terms risk must combine with pricing risk into one approval level, recomputed on every calculation | QCP `termsReview` + `ContractTerms` |
| Contract lifecycle + renewal notices | Notice dates depend on per-contract notice periods and auto-renew; a renewal must go through the Renewer with prior-price facts, not CPQ's checkbox-triggered default | `ContractLifecycle`, `RenewalNotice`, `RenewalNoticeJob` |

Still configuration, on purpose: products, bundles and options, price books, discount schedules,
standard price rules, quote templates, and the Advanced Approvals rules and chains.

## Rules for code that touches CPQ

1. **Go through the calculator.** Code never writes `SBQQ__NetPrice__c` or other calculated fields. It
   changes inputs (quantity, special price, custom facts) and lets CPQ calculate through the Quote API.
2. **Pure logic stays out of the package.** `force-app-core` has no SBQQ references and deploys to any
   org, so the rules are unit-tested without CPQ data setup.
3. **One test suite, two runtimes.** `vectors/pricing-vectors.json` runs in node against the QCP and in
   Apex against `Pricing`. When both pass, the browser calculator and server automation agree.
4. **The trigger handler works on in-memory records.** No queries or DML, so it's testable without
   CPQ's own triggers and calculator firing.
5. **Everything is invocable.** Admins compose amend, renew, submit and estimate in Flow, without
   another code change.

## Known trade-offs

- The QCP's arithmetic is JavaScript floating point rounded to cents. Apex uses Decimal. The vectors
  include month-end and rounding edge cases to catch divergence.
- `calculateAndSave` is asynchronous. A flow that creates an amendment and immediately reads its
  totals sees pre-calculation values. The flow should wait on the quote's calculation status.
- Proration conventions in `Pricing` must match the org's CPQ *Subscription Prorate Precision* setting.
  CPQ computes the real amendment amounts; `CoTermEstimator` is only an estimate.
