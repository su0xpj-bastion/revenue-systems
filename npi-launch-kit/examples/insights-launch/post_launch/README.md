# Post-launch exports (seeded with defects)

Fictional first-month exports from CPQ, Salesforce orders, billing and the finance report.
Six defects are planted on purpose, one per control: each should be caught.

| Control | Planted defect |
|---|---|
| quote_vs_order | Q-1003 quoted 6000, ordered 6600 |
| accepted_quote_without_order | Q-1004 accepted, never ordered |
| order_not_invoiced | O-2003 never invoiced |
| tax_code_mismatch | I-3002 has no tax code |
| finance_report_vs_billing | INS-ENT billed 60000, finance report shows 0 (reporting map gap) |
| retired_sku_on_new_business | Q-1005 quotes LEGACY-ANALYTICS to a new customer after end of sale |

Q-1006 is a renewal on the retired SKU before end-of-renewal. It is allowed and must NOT be flagged.
