# Control matrix

Audience: internal audit, external auditors, and controllers. Each control runs per billing period
(`m2r controls BOOK PERIOD`) and writes `evidence.json`, `evidence.sha256` and `evidence.md`.
An empty exception list is the evidence the control operated and passed.

| ID | Control | Risk addressed | Nature | How it operates | Evidence |
|---|---|---|---|---|---|
| C-01 | Usage batch completeness | Usage lost between metering and billing → revenue leakage | Detective | Each batch's received event count and quantity sum must equal the producer's manifest. Rejected events are exceptions | Batch table: manifest vs received, duplicates, rejected, late |
| C-02 | Usage billed exactly once | Double billing from producer retries; usage never billed | Preventive + detective | Event id is the primary key (retries rejected). An event links to one invoice only, set once in the same transaction as the invoice. Detective check: no accepted event before period end is left unbilled | Duplicates rejected, events billed |
| C-03 | Rating accuracy | Pricing logic errors | Detective | Every usage line is re-rated from its own events by an independently written algorithm | Lines checked, any differences |
| C-04 | Invoice immutability | Invoices changed after finalization | Detective | Each finalized invoice's SHA-256 over canonical JSON is recomputed. Corrections go through new documents, never edits | Invoices checked |
| C-05 | Tax determination | Untaxed taxable sales; undocumented exemptions | Detective (the billing run is preventive and fails closed) | Every line has a tax code and an engine note; zero tax on a taxable line needs an exemption certificate | Exceptions per line |
| C-06 | Deferred revenue roll-forward | Revenue recognized early or late; schedule out of sync with GL | Detective | Beginning + billed − released = ending, and ending must equal the GL deferred revenue balance | Roll-forward table per period |
| C-07 | Subledger to GL | Billing and ledger disagree; unbalanced entries | Detective | Period invoice totals must equal AR debits, and every journal entry must balance | Invoice total, GL AR, entry count |
| C-08 | Price-change segregation of duties | Unauthorized or self-approved pricing | Detective (the preventive version is the CPQ approval process) | Every contract price or quantity change needs an approver who is not the requester | Changes reviewed, exceptions |

## Design choices an auditor will ask about

- **Why no invoice edits?** Changing a finalized invoice destroys the record of what the customer was
  billed. Late usage goes on the next invoice and is labeled prior-period. Errors get a correcting
  document. C-04 proves nothing was edited.
- **Why re-rate with a second implementation?** Comparing a calculation to itself proves nothing.
  C-03's re-rater shares no code with the billing rater.
- **Why fail closed on tax?** An invoice with silently-zero tax is a liability nobody sees. Missing
  jurisdiction or code data stops the run before anything is written (the test suite checks nothing half-written remains).
- **Atomic billing runs.** Invoices, event→invoice links and the run marker commit in one transaction.
  A period can't be billed twice or out of order.
- **Evidence integrity.** The evidence JSON is hashed. In production, store the pack and its hash in
  write-once storage outside the system that produced it.

## Limits

- C-06 compares the schedule to a journal this system generates. In production the GL side comes
  from the ERP export, which is what makes the tie-out independent.
- C-08 reads a change log export. The preventive control is the CPQ approval process; this control
  catches anything that bypassed it.
