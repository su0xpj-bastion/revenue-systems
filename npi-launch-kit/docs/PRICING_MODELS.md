# Pricing models end to end

How each model flows through quote → booking → invoice → tax → revenue, and which system is
the source of truth for each part.

## Source of truth

| Data | Source of truth | Why |
|---|---|---|
| SKU, name, family, active, end of sale | Salesforce `Product2` | Sellers and Deal Desk work from it; everything else syncs from it |
| List price, tiers, bundles, approval rules | CPQ (price book, discount schedules, options) | Price is decided at quote time |
| Contracted price, quantity, term, ramp | Order / contract in Salesforce | What the customer signed |
| Usage quantities | Metering service | Only the system that observes usage can count it |
| Invoice amounts, payment state | Billing platform | Billing applies the contract to usage |
| Tax code | Salesforce `Product2.Tax_Code__c`, mirrored in the tax engine | Tax owns the value; the reconciliation control checks they agree |
| Tax amount | Tax engine | Jurisdiction rules live there |
| Revenue schedule | ERP / revenue system | Accounting policy lives there |

## Models

### Per seat (`per_seat`)
- **Quote**: seats × monthly price × term; minimum quantity enforced.
- **Booking**: ACV = 12 × monthly price × seats.
- **Invoice**: in advance, once per billing period.
- **Revenue**: ratable over the term.
- **Watch for**: mid-term seat adds need co-termed proration (`coterm_proration`, monthly + daily).

### Usage, tiered (`usage_tiered`)
- **Quote**: rate card only; no committed amount.
- **Booking**: none. Consumption shows up as billed revenue.
- **Invoice**: monthly in arrears from metered quantities. **Graduated**: each tier's units at that tier's
  price. **Volume**: all units at the price of the tier the total lands in.
- **Revenue**: as consumed.
- **Watch for**: a metering feed late at bill run means a late or missing invoice. Reconciliation catches missing lines.

### Committed with ramp (`committed`)
- **Quote**: commit per contract year (ramp), drawdown rate, overage rate.
- **Booking**: ACV per ramp year; TCV = sum of the ramp.
- **Invoice**: each year's commit in advance. Usage draws down at the drawdown rate; past the commit,
  overage bills monthly in arrears at the overage rate.
- **Revenue**: as consumed; unused commit is recognized as breakage at year end (Accounting confirms).
- **Watch for**: overage cheaper than drawdown, overage above pay-as-you-go list, and quoting PAYG and commit
  for the same usage on one quote. The linter or engine flags all three.

### Flat (`flat`)
- Monthly fee × term, billed per billing frequency, ratable.

## Worked examples (the scenario suite's expected values)

Each was worked by hand before it went into `examples/insights-launch/scenarios.yaml`.

**Team, 10 seats, 15% off, annual billing**: 10 × $30 × 12 × 0.85 = **$3,060.00**, one invoice.
15% falls in the 10–20% band, so it goes to **Deal Desk**.

**API usage 50, 100, 101, 1,500 (M tokens), graduated $3.00 / $2.50 / $2.00 at 100 / 1,000**
- 50 × 3.00 = 150.00
- 100 × 3.00 = 300.00
- 100 × 3.00 + 1 × 2.50 = 302.50
- 100 × 3.00 + 900 × 2.50 + 500 × 2.00 = 3,550.00
- Total **$4,302.50**; first invoice **$150.00**

**Enterprise commit, 3,500 units every month in year 1** (drawdown $2.00, overage $2.25)
- Each month consumes 3,500 × 2.00 = $7,000 of the $60,000 commit
- After 8 months: $56,000 used. Month 9 needs $7,000 but only $4,000 is left, so 2,000 units are covered and **1,500 units are overage** = $3,375.00
- Months 10–12: 3,500 × 2.25 = $7,875.00 each = $23,625.00
- Year 1 = 60,000 + 3,375 + 23,625 = 87,000. Years 2–3 commits = 90,000 + 120,000
- Total **$297,000.00**; first invoice **$60,000.00** (year-1 commit in advance)

**Co-term proration**: 10 seats at $30 added on Apr 15 to a term ending Jul 1: 2 whole months
(Apr 15 → Jun 15) + 16/30 of June = 2.5333 months × $300 = **$760.00**.
