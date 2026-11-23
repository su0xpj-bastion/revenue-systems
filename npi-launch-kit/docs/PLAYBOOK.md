# NPI playbook (systems)

The systems owner of a launch is accountable for one outcome: on launch day a seller can quote it,
Deal Desk can approve it, billing charges it correctly, tax is right, and Finance can report it.
Then the first billing cycle proves all of that is true.

## Timeline

| When | Step | Exit criteria | Tool |
|---|---|---|---|
| As early as possible | **Join pricing discussions** | Systems constraints raised before the price is decided | `validate` on early drafts |
| T-60 → T-45 | **Intake** | Brief received; spec drafted; open questions owned | `draft`, `validate` |
| T-45 | **Spec frozen** | `validate` has 0 blocking findings; warnings accepted in writing | `validate` |
| T-45 → T-30 | **Build** | Catalog loaded in sandbox; declarative changes built; dev specs handed off | `catalog` |
| T-30 → T-14 | **Test** | Scenario suite passes against the sandbox quote engine and billing | `scenarios`, `propose-scenarios` |
| T-21 → T-14 | **Existing customers** | Migration plan approved; CS has the outreach list | `migrate` |
| T-14 → T-7 | **Sign-offs** | Every team in `signoffs` signs what changes *for them* | `readiness` |
| T-7 | **Enablement** | Seller guidance, quote templates, Deal Desk approval paths live | `readiness` |
| T-0 | **Launch** | Activate in production price book; old SKUs to End of Sale | `readiness` = GO |
| T+3 | **First quotes** | First live quotes match expected pricing | `scenarios` vs real quotes |
| First bill run +5 | **Reconcile** | All controls clean or each failure owned | `reconcile` |
| T+45 | **Post-launch review** | What broke, what nearly did, which control or lint rule prevents it next time | — |

## Intake: what the brief must answer

Each of these becomes a spec field or an open question. A launch doesn't freeze with open questions.

1. What is being sold (SKUs, bundles) and to whom?
2. How is each SKU priced: flat, per seat, usage tiers (graduated or volume), commit with ramp?
3. Term, billing frequency, in advance or in arrears?
4. For usage: which system is the source of truth for quantities?
5. For commits: drawdown rate, overage rate, does unused commit roll over?
6. Discount bands and who approves each.
7. Tax treatment (Tax provides the codes; nobody guesses them).
8. Revenue treatment (Accounting confirms).
9. What happens to existing customers on SKUs this replaces?
10. Launch date, and the first bill run that will include it.

## Pushing back on pricing

The linter turns systems constraints into named, specific findings. Each one names the team that owns the
decision, so the conversation is about a decision, not about "the system can't do it". Examples:

- *"Overage is cheaper than committed usage."* This rewards customers for under-committing. Pricing decides.
- *"No source of truth for usage."* Billing can't invoice what nobody meters. Billing Engineering decides.
- *"18-month term can't be billed in whole annual periods."* Offer 12 or 24, or quarterly billing. Pricing decides.
- *"Old SKU stops selling before its replacement launches."* Sellers would have nothing to quote. Product decides.

Push back with options, not a no. Every finding should come with at least one shape that *can* be built.

## Sign-offs: what each team signs

| Team | Signs that… |
|---|---|
| Product | SKUs, bundles and the retirement plan match the launch |
| Pricing | Prices, tiers, ramps and discount bands are as decided |
| Deal Desk | Approval paths, quote templates and non-standard-deal guidance are ready |
| Sales | Sellers are enabled and know what changes in their quotes |
| Finance | Scenario totals are right; bookings and reporting map are right |
| Accounting | Revenue treatment per SKU is right, including commit breakage |
| Tax | Every SKU has the right tax code, and it's mapped in the tax engine |
| Legal | Order form and terms cover commits, ramps, overage and migration |
| Billing Eng | Billing plans, usage feeds and invoice templates are configured and tested |

## Spec for developers

When part of a launch needs code (triggers, integrations, billing plan logic), hand off a spec that
answers these without a meeting:

- **Trigger**: what event, on which object or system
- **Inputs**: fields and sources, with an example record or payload
- **Rules**: the decision table, drawn from the launch spec, not restated in prose
- **Outputs**: records created or updated, and messages sent
- **Errors**: what happens on bad input, partial failure, or retry
- **Acceptance**: the scenario IDs from the suite that must pass
- **Out of scope**: written down, so nobody builds it

## Post-launch review template

1. Did every reconciliation control come back clean on the first bill run? If not, why didn't the readiness checklist catch it?
2. Which sign-off was late, and what would have made it earlier?
3. Which questions came up after spec freeze? Add each to the intake list.
4. Which manual step could be generated from the spec next time?
5. New lint rule or reconciliation control from this launch: ______
