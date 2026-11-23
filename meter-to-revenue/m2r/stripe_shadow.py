"""Stripe Billing shadow: mirror the catalog and usage into Stripe TEST mode and check parity.

Two parity checks, each a detective control against a second billing system:
- catalog parity: every Stripe price, read back from Stripe, matches the book (amounts, interval,
  tier boundaries, graduated vs volume)
- usage parity: Stripe's aggregated meter totals per customer equal what this system ingested

Safety: refuses any key that is not a test-mode key. Creates are sent with idempotency keys and
meter events with the source event id as `identifier`, so re-running cannot double-count.

The `stripe` module is passed in, so tests run against a fake and nothing here imports it at
module load. This adapter is unit-tested against a fake; run it against your own Stripe test
account before relying on it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from .model import Book, Product
from .store import Store


class LiveKeyError(PermissionError):
    pass


def require_test_key(key: str | None) -> str:
    if not key or not (key.startswith("sk_test_") or key.startswith("rk_test_")):
        raise LiveKeyError("refusing to run: STRIPE_API_KEY must be a test-mode key (sk_test_ / rk_test_)")
    return key


def cents(amount: Decimal) -> str:
    """Stripe's *_decimal fields take plain decimal strings in cents; never exponent notation."""
    text = f"{amount * 100:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _interval(book: Book, code: str) -> str:
    annual = any(l.product == code and l.billing == "annual" for c in book.contracts for l in c.lines)
    return "year" if annual else "month"


def price_params(product: Product, interval: str, meter_id: str | None) -> dict:
    if product.kind in ("seat", "flat"):
        multiplier = 12 if interval == "year" else 1
        return {"currency": "usd", "unit_amount_decimal": cents(product.unit_price * multiplier),
                "recurring": {"interval": interval, "usage_type": "licensed"}}
    return {
        "currency": "usd",
        "billing_scheme": "tiered",
        "tiers_mode": product.tier_mode,
        "tiers": [{"up_to": "inf" if t.up_to is None else int(t.up_to),
                   "unit_amount_decimal": cents(t.unit_price)} for t in product.tiers],
        "recurring": {"interval": "month", "usage_type": "metered", "meter": meter_id},
    }


def sync_catalog(stripe, book: Book) -> dict[str, dict]:
    ids: dict[str, dict] = {}
    for product in book.products.values():
        sp = stripe.Product.create(name=product.name, metadata={"m2r_code": product.code},
                                   idempotency_key=f"m2r-product-{product.code}")
        entry = {"product": sp.id}
        meter_id = None
        if product.kind == "usage":
            meter = stripe.billing.Meter.create(
                display_name=product.name, event_name=product.meter,
                default_aggregation={"formula": "sum"},
                customer_mapping={"type": "by_id", "event_payload_key": "stripe_customer_id"},
                value_settings={"event_payload_key": "value"},
                idempotency_key=f"m2r-meter-{product.meter}",
            )
            meter_id = entry["meter"] = meter.id
        interval = _interval(book, product.code)
        price = stripe.Price.create(product=sp.id, metadata={"m2r_code": product.code},
                                    idempotency_key=f"m2r-price-{product.code}-{interval}",
                                    **price_params(product, interval, meter_id))
        entry["price"], entry["interval"] = price.id, interval
        ids[product.code] = entry
    for customer in book.customers.values():
        sc = stripe.Customer.create(name=customer.name, metadata={"m2r_id": customer.id},
                                    idempotency_key=f"m2r-customer-{customer.id}")
        ids[customer.id] = {"customer": sc.id}
    return ids


def catalog_parity(stripe, book: Book, ids: dict[str, dict]) -> list[str]:
    exceptions = []
    for product in book.products.values():
        entry = ids.get(product.code)
        if not entry:
            exceptions.append(f"{product.code}: not synced")
            continue
        got = stripe.Price.retrieve(entry["price"], expand=["tiers"])
        want = price_params(product, entry["interval"], entry.get("meter"))
        if got.recurring["interval"] != want["recurring"]["interval"]:
            exceptions.append(f"{product.code}: interval {got.recurring['interval']} != {want['recurring']['interval']}")
        if product.kind == "usage":
            if got.tiers_mode != want["tiers_mode"]:
                exceptions.append(f"{product.code}: tiers_mode {got.tiers_mode} != {want['tiers_mode']}")
            got_tiers = [(t["up_to"] if t["up_to"] is not None else "inf", Decimal(str(t["unit_amount_decimal"])))
                         for t in got.tiers]
            want_tiers = [(t["up_to"], Decimal(t["unit_amount_decimal"])) for t in want["tiers"]]
            if got_tiers != want_tiers:
                exceptions.append(f"{product.code}: tiers {got_tiers} != {want_tiers}")
        elif Decimal(str(got.unit_amount_decimal)) != Decimal(want["unit_amount_decimal"]):
            exceptions.append(f"{product.code}: amount {got.unit_amount_decimal} != {want['unit_amount_decimal']}")
    return exceptions


def push_usage(stripe, book: Book, store: Store, ids: dict[str, dict], start_iso: str, end_iso: str) -> int:
    """Send ingested events in [start, end) as meter events. Stripe only accepts recent timestamps,
    so a live demo needs fresh events; the source event id makes resends harmless."""
    sent = 0
    for e in store.all_events():
        if not (start_iso <= e["ts"] < end_iso):
            continue
        ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00")).astimezone(timezone.utc)
        stripe.billing.MeterEvent.create(
            event_name=e["meter"], identifier=e["event_id"], timestamp=int(ts.timestamp()),
            payload={"stripe_customer_id": ids[e["customer"]]["customer"], "value": e["quantity"]},
        )
        sent += 1
    return sent


def usage_parity(stripe, book: Book, store: Store, ids: dict[str, dict], start_iso: str, end_iso: str) -> list[str]:
    start = int(datetime.fromisoformat(start_iso.replace("Z", "+00:00")).timestamp())
    end = int(datetime.fromisoformat(end_iso.replace("Z", "+00:00")).timestamp())
    ours: dict[tuple[str, str], Decimal] = {}
    for e in store.all_events():
        if start_iso <= e["ts"] < end_iso:
            key = (e["customer"], e["meter"])
            ours[key] = ours.get(key, Decimal(0)) + Decimal(e["quantity"])
    exceptions = []
    for (customer, meter), quantity in sorted(ours.items()):
        product = book.product_for_meter(meter)
        summaries = stripe.billing.Meter.list_event_summaries(
            ids[product.code]["meter"], customer=ids[customer]["customer"], start_time=start, end_time=end)
        theirs = sum((Decimal(str(s["aggregated_value"])) for s in summaries.data), Decimal(0))
        if theirs != quantity:
            exceptions.append(f"{customer} {meter}: ours {quantity}, Stripe {theirs}")
    return exceptions
