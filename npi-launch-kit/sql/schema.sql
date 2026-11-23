-- Post-launch reconciliation schema. Loaded from CSV exports of each system.

CREATE TABLE catalog (          -- from the launch spec
    sku TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    tax_code TEXT,
    family TEXT
);

CREATE TABLE retirements (      -- from the launch spec
    sku TEXT PRIMARY KEY,
    end_of_sale TEXT NOT NULL
);

CREATE TABLE quote_lines (      -- CPQ export
    quote_id TEXT NOT NULL,
    account TEXT NOT NULL,
    quote_date TEXT NOT NULL,
    opportunity_type TEXT NOT NULL,
    status TEXT NOT NULL,
    sku TEXT NOT NULL,
    first_period_amount REAL NOT NULL
);

CREATE TABLE order_lines (      -- Salesforce orders
    order_id TEXT NOT NULL,
    quote_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    first_period_amount REAL NOT NULL
);

CREATE TABLE invoice_lines (    -- billing system export
    invoice_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    period TEXT NOT NULL,       -- YYYY-MM
    sku TEXT NOT NULL,
    amount REAL NOT NULL,
    tax_code TEXT,
    tax_amount REAL
);

CREATE TABLE finance_report (   -- warehouse / ERP revenue report
    period TEXT NOT NULL,
    sku TEXT NOT NULL,
    billed REAL NOT NULL
);
