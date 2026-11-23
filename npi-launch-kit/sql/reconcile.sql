-- Post-launch controls. Each query returns the rows that FAIL the control; empty = clean.
-- Run after the first bill run of every launch, then monthly as a standing control.

-- name: quote_vs_order
-- Accepted quote line and its order line disagree on the first-period amount.
SELECT q.quote_id, o.order_id, q.sku,
       q.first_period_amount AS quoted, o.first_period_amount AS ordered
FROM quote_lines q
JOIN order_lines o ON o.quote_id = q.quote_id AND o.sku = q.sku
WHERE q.status = 'Accepted'
  AND ABS(q.first_period_amount - o.first_period_amount) > 0.005;

-- name: accepted_quote_without_order
SELECT q.quote_id, q.account, q.sku, q.first_period_amount
FROM quote_lines q
LEFT JOIN order_lines o ON o.quote_id = q.quote_id AND o.sku = q.sku
WHERE q.status = 'Accepted' AND o.order_id IS NULL;

-- name: order_not_invoiced
-- Fixed-fee and commit order lines with no invoice on the first bill run.
SELECT o.order_id, o.sku, o.first_period_amount
FROM order_lines o
JOIN catalog c ON c.sku = o.sku AND c.model IN ('flat', 'per_seat', 'committed')
LEFT JOIN invoice_lines i ON i.order_id = o.order_id AND i.sku = o.sku
WHERE i.invoice_id IS NULL;

-- name: invoice_vs_order
-- First-period invoice amount differs from the ordered first-period amount.
SELECT o.order_id, o.sku, o.first_period_amount AS ordered, SUM(i.amount) AS invoiced
FROM order_lines o
JOIN catalog c ON c.sku = o.sku AND c.model IN ('flat', 'per_seat', 'committed')
JOIN invoice_lines i ON i.order_id = o.order_id AND i.sku = o.sku
                    AND i.period = (SELECT MIN(period) FROM invoice_lines WHERE order_id = o.order_id)
GROUP BY o.order_id, o.sku, o.first_period_amount
HAVING ABS(o.first_period_amount - SUM(i.amount)) > 0.005;

-- name: tax_code_mismatch
-- Invoice taxed with no code or a code other than the catalog's.
SELECT i.invoice_id, i.sku, i.tax_code AS invoiced_code, c.tax_code AS catalog_code
FROM invoice_lines i
JOIN catalog c ON c.sku = i.sku
WHERE i.tax_code IS NULL OR i.tax_code = '' OR i.tax_code <> c.tax_code;

-- name: invoice_unknown_sku
SELECT i.invoice_id, i.sku, i.amount
FROM invoice_lines i
LEFT JOIN catalog c ON c.sku = i.sku
LEFT JOIN retirements r ON r.sku = i.sku
WHERE c.sku IS NULL AND r.sku IS NULL;

-- name: finance_report_vs_billing
-- Finance's billed revenue per SKU and period disagrees with the billing system.
SELECT COALESCE(f.period, b.period) AS period, COALESCE(f.sku, b.sku) AS sku,
       f.billed AS finance_billed, b.billed AS billing_billed
FROM finance_report f
FULL OUTER JOIN (
    SELECT period, sku, ROUND(SUM(amount), 2) AS billed FROM invoice_lines GROUP BY period, sku
) b ON b.period = f.period AND b.sku = f.sku
WHERE f.billed IS NULL OR b.billed IS NULL OR ABS(f.billed - b.billed) > 0.005;

-- name: retired_sku_on_new_business
-- A retired SKU was quoted on new business after its end-of-sale date.
SELECT q.quote_id, q.account, q.sku, q.quote_date, r.end_of_sale
FROM quote_lines q
JOIN retirements r ON r.sku = q.sku
WHERE q.quote_date >= r.end_of_sale
  AND q.opportunity_type NOT LIKE '%Renewal%';
