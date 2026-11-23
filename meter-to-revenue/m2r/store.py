"""SQLite store for usage events, batches and finalized invoices.

Preventive controls live in the schema: the event id is the primary key (a resent event cannot
be stored twice), and an event can be billed exactly once (billed_invoice_id is set once).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    manifest_count INTEGER NOT NULL,
    manifest_quantity TEXT NOT NULL,
    received_count INTEGER NOT NULL,
    received_quantity TEXT NOT NULL,
    accepted INTEGER NOT NULL,
    duplicates INTEGER NOT NULL,
    rejected INTEGER NOT NULL,
    late INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS usage_events (
    event_id TEXT PRIMARY KEY,           -- idempotency key from the producer
    customer TEXT NOT NULL,
    meter TEXT NOT NULL,
    quantity TEXT NOT NULL,
    ts TEXT NOT NULL,
    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
    billed_invoice_id TEXT
);
CREATE TABLE IF NOT EXISTS invoices (
    invoice_id TEXT PRIMARY KEY,
    contract_id TEXT NOT NULL,
    period TEXT NOT NULL,
    body TEXT NOT NULL,                  -- canonical JSON
    sha256 TEXT NOT NULL,
    UNIQUE (contract_id, period)
);
CREATE TABLE IF NOT EXISTS billing_runs (
    period TEXT PRIMARY KEY,
    invoice_count INTEGER NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # --- events -------------------------------------------------------------
    def insert_event(self, event: dict, batch_id: str) -> bool:
        cursor = self.db.execute(
            "INSERT OR IGNORE INTO usage_events (event_id, customer, meter, quantity, ts, batch_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (event["event_id"], event["customer"], event["meter"], str(event["quantity"]),
             event["timestamp"], batch_id),
        )
        return cursor.rowcount == 1

    def unbilled_events(self, customer: str, meter: str, before_iso: str) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM usage_events WHERE customer = ? AND meter = ? AND ts < ? "
            "AND billed_invoice_id IS NULL ORDER BY ts, event_id",
            (customer, meter, before_iso),
        ).fetchall()

    def events_for_invoice(self, invoice_id: str) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM usage_events WHERE billed_invoice_id = ? ORDER BY ts", (invoice_id,)
        ).fetchall()

    def all_events(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM usage_events ORDER BY ts, event_id").fetchall()

    def add_batch(self, row: dict) -> None:
        self.db.execute(
            "INSERT INTO batches VALUES (:batch_id, :source, :manifest_count, :manifest_quantity, "
            ":received_count, :received_quantity, :accepted, :duplicates, :rejected, :late)", row,
        )
        self.db.commit()

    def batches(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM batches ORDER BY batch_id").fetchall()

    # --- invoices -----------------------------------------------------------
    def period_billed(self, period: str) -> bool:
        return self.db.execute("SELECT 1 FROM billing_runs WHERE period = ?", (period,)).fetchone() is not None

    def billed_periods(self) -> list[str]:
        return [r["period"] for r in self.db.execute("SELECT period FROM billing_runs ORDER BY period")]

    def save_run(self, period: str, invoices: list[tuple[dict, str]], event_bills: dict[str, str]) -> None:
        """Finalize a billing run atomically: invoices, event → invoice links, run marker."""
        with self.db:
            for body, digest in invoices:
                self.db.execute(
                    "INSERT INTO invoices VALUES (?, ?, ?, ?, ?)",
                    (body["invoice_id"], body["contract_id"], body["period"],
                     json.dumps(body, sort_keys=True, separators=(",", ":")), digest),
                )
            for event_id, invoice_id in event_bills.items():
                cursor = self.db.execute(
                    "UPDATE usage_events SET billed_invoice_id = ? WHERE event_id = ? AND billed_invoice_id IS NULL",
                    (invoice_id, event_id),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(f"event {event_id} already billed")
            self.db.execute("INSERT INTO billing_runs VALUES (?, ?)", (period, len(invoices)))

    def invoices(self, through_period: str | None = None) -> list[dict]:
        sql, args = "SELECT body FROM invoices", ()
        if through_period:
            sql, args = sql + " WHERE period <= ?", (through_period,)
        return [json.loads(r["body"]) for r in self.db.execute(sql + " ORDER BY period, invoice_id", args)]

    def invoice_rows(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM invoices ORDER BY period, invoice_id").fetchall()
