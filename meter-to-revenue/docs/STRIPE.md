# Stripe shadow billing

Running a second billing system against the same contracts and usage is one of the strongest
accuracy controls available. Two independently built systems rarely make the same mistake.
`m2r.stripe_shadow` mirrors the book into a **Stripe test-mode** account and checks parity.

## Mapping

| Book | Stripe |
|---|---|
| Product | `Product` (`metadata.m2r_code`) |
| Seat / flat, monthly | `Price`: `recurring.interval=month`, `usage_type=licensed`, `unit_amount_decimal` in cents |
| Seat, annual | `Price`: `recurring.interval=year`, amount × 12 |
| Usage product + meter | `billing.Meter` (`default_aggregation.formula=sum`, customer mapped by payload key) and a tiered `Price` with `billing_scheme=tiered`, `tiers_mode=graduated|volume`, `recurring.usage_type=metered`, `recurring.meter` |
| Tier `up_to: null` | `up_to: "inf"` |
| Customer | `Customer` (`metadata.m2r_id`) |
| Usage event | `billing.MeterEvent` with `identifier = event_id` (Stripe de-duplicates on it) |

Creates use idempotency keys derived from book codes, so re-running sync doesn't create duplicates
within Stripe's idempotency window.

## Parity checks

- **Catalog parity**: every price read back from Stripe (tiers expanded) must match the book:
  interval, amount, tiers mode, and each tier's bound and unit amount.
- **Usage parity**: for each customer and meter, Stripe's `list_event_summaries` aggregate over the
  window must equal what this system ingested.

## Safety

- Keys must start with `sk_test_` or `rk_test_`; anything else raises before a client exists.
- The adapter never creates subscriptions or invoices, so nothing is ever charged, even in test mode.

## Status

Unit-tested against a fake Stripe module that records calls. **Not yet run against a live Stripe test account.**
Stripe accepts meter events only with recent timestamps, so a live run needs freshly generated events.

## Equivalents in other billing platforms

| Concept here | Metronome | Zuora |
|---|---|---|
| Meter + usage events | Billable metric + ingested events | Usage records |
| Tiered usage price | Rate card rate (tiered) | Tiered / volume charge model |
| Prepaid commit + credit applied | Prepaid commit (drawdown) | Prepaid with drawdown |
| Breakage at expiry | Commit expiry | Drawdown expiry |

Only the Stripe adapter is implemented. The other columns are mappings, not code.
