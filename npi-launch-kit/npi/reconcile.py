"""Post-launch reconciliation: do quotes, orders, invoices and the finance report agree?

Loads CSV exports into SQLite and runs the controls in sql/reconcile.sql. The SQL is the
artifact: it ports to the warehouse unchanged apart from table names.
"""
from __future__ import annotations

import csv
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .spec import Launch

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
SOURCES = ("quote_lines", "order_lines", "invoice_lines", "finance_report")


@dataclass
class ControlResult:
    name: str
    description: str
    columns: list[str]
    rows: list[tuple]

    @property
    def passed(self) -> bool:
        return not self.rows


def parse_queries(sql: str) -> list[tuple[str, str, str]]:
    """Split a file of `-- name: x` blocks into (name, description, sql)."""
    queries = []
    for block in re.split(r"^-- name: ", sql, flags=re.MULTILINE)[1:]:
        name, _, body = block.partition("\n")
        comments = [l[2:].strip() for l in body.splitlines() if l.startswith("--")]
        queries.append((name.strip(), " ".join(comments), body.strip()))
    return queries


def connect(launch: Launch, data_dir: Path) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.executescript((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
    db.executemany(
        "INSERT INTO catalog VALUES (?, ?, ?, ?)",
        [(p.sku, p.model, p.tax_code, p.family) for p in launch.products],
    )
    db.executemany(
        "INSERT INTO retirements VALUES (?, ?)",
        [(r.sku, r.end_of_sale.isoformat()) for r in launch.retirements],
    )
    for table in SOURCES:
        path = Path(data_dir) / f"{table}.csv"
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames
            rows = [tuple(row[c] if row[c] != "" else None for c in columns) for row in reader]
        placeholders = ", ".join("?" for _ in columns)
        db.executemany(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", rows)
    return db


def run_controls(launch: Launch, data_dir: Path) -> list[ControlResult]:
    db = connect(launch, data_dir)
    results = []
    for name, description, sql in parse_queries((SQL_DIR / "reconcile.sql").read_text(encoding="utf-8")):
        cursor = db.execute(sql)
        results.append(ControlResult(
            name, description, [c[0] for c in cursor.description], cursor.fetchall()
        ))
    return results


def render(results: list[ControlResult]) -> str:
    lines = ["# Post-launch reconciliation", ""]
    failed = [r for r in results if not r.passed]
    lines.append(f"{len(results) - len(failed)}/{len(results)} controls clean.")
    for r in results:
        lines += ["", f"## {'✅' if r.passed else '❌'} {r.name}", "", r.description]
        if r.rows:
            lines += ["", "| " + " | ".join(r.columns) + " |", "|" + "---|" * len(r.columns)]
            lines += ["| " + " | ".join("" if v is None else str(v) for v in row) + " |" for row in r.rows]
    return "\n".join(lines) + "\n"
