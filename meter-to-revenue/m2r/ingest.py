"""Usage ingestion: validate, de-duplicate by idempotency key, reconcile to the batch manifest.

Each batch arrives as events.jsonl plus a manifest from the producer (count and quantity sum).
Duplicates (a producer resending after a timeout) are rejected by the store's primary key.
Late events (timestamped in a period already billed) are accepted and billed in the next run
as prior-period usage, never by editing a finalized invoice.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .model import Book, period_of, as_date
from .store import Store

REQUIRED = ("event_id", "customer", "meter", "quantity", "timestamp")


@dataclass
class BatchResult:
    batch_id: str
    accepted: int = 0
    duplicates: int = 0
    late: int = 0
    rejected: list[str] = field(default_factory=list)
    manifest_count: int = 0
    received_count: int = 0
    manifest_quantity: Decimal = Decimal(0)
    received_quantity: Decimal = Decimal(0)

    @property
    def complete(self) -> bool:
        return (self.manifest_count == self.received_count
                and self.manifest_quantity == self.received_quantity)


def validate_event(event: dict, book: Book) -> str | None:
    missing = [k for k in REQUIRED if event.get(k) in (None, "")]
    if missing:
        return f"missing {missing}"
    if event["customer"] not in book.customers:
        return f"unknown customer {event['customer']}"
    if book.product_for_meter(event["meter"]) is None:
        return f"unknown meter {event['meter']}"
    try:
        quantity = Decimal(str(event["quantity"]))
    except InvalidOperation:
        return f"quantity {event['quantity']!r} is not a number"
    if quantity < 0:
        return "negative quantity (corrections go through credit notes, not negative usage)"
    try:
        as_date(str(event["timestamp"])[:10])
    except ValueError:
        return f"bad timestamp {event['timestamp']!r}"
    return None


def ingest_batch(store: Store, book: Book, batch_dir: Path) -> BatchResult:
    batch_dir = Path(batch_dir)
    manifest = json.loads((batch_dir / "manifest.json").read_text(encoding="utf-8"))
    result = BatchResult(
        batch_id=manifest["batch_id"],
        manifest_count=int(manifest["count"]),
        manifest_quantity=Decimal(str(manifest["quantity_sum"])),
    )
    billed = set(store.billed_periods())
    with (batch_dir / "events.jsonl").open("r", encoding="utf-8") as f:
        events = [json.loads(line) for line in f if line.strip()]

    for event in events:
        result.received_count += 1
        problem = validate_event(event, book)
        if problem:
            result.rejected.append(f"{event.get('event_id', '?')}: {problem}")
            continue
        result.received_quantity += Decimal(str(event["quantity"]))
        if not store.insert_event(event, result.batch_id):
            result.duplicates += 1
            continue
        result.accepted += 1
        if period_of(as_date(event["timestamp"][:10])) in billed:
            result.late += 1

    store.add_batch({
        "batch_id": result.batch_id, "source": manifest.get("source", ""),
        "manifest_count": result.manifest_count, "manifest_quantity": str(result.manifest_quantity),
        "received_count": result.received_count, "received_quantity": str(result.received_quantity),
        "accepted": result.accepted, "duplicates": result.duplicates,
        "rejected": len(result.rejected), "late": result.late,
    })
    return result
