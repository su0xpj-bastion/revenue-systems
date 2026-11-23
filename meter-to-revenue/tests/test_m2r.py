import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from m2r import controls as ctl
from m2r.billing import BillingError, run_billing
from m2r.ingest import ingest_batch
from m2r.model import BookError, load_book
from m2r.rating import rate_usage, rerate_independently
from m2r.revenue import allocate_by_days, journal, roll_forward, schedules, trial_balance, AR, DEFERRED, REVENUE, TAX
from m2r.store import Store
from m2r.stripe_shadow import LiveKeyError, catalog_parity, price_params, push_usage, require_test_key, sync_catalog, usage_parity
from m2r.tax import RateTableProvider, TaxError

EXAMPLE = Path(__file__).resolve().parent.parent / "example"
D = Decimal


@pytest.fixture
def book():
    return load_book(EXAMPLE)


def run_period(book, store, period):
    ingest_batch(store, book, EXAMPLE / "usage" / f"batch-{period}")
    return {inv["contract_id"]: inv for inv in run_billing(book, store, period, RateTableProvider(book.tax_rates))}


@pytest.fixture
def billed(book):
    store = Store()
    march = run_period(book, store, "2027-03")
    april = run_period(book, store, "2027-04")
    return store, march, april


def lines(inv, kind):
    return [l for l in inv["lines"] if l["kind"] == kind]


# --- ingestion ----------------------------------------------------------------

def test_duplicate_event_rejected_and_counted(book):
    store = Store()
    r = ingest_batch(store, book, EXAMPLE / "usage" / "batch-2027-03")
    assert (r.accepted, r.duplicates, r.complete) == (5, 1, True)


def test_reingesting_a_batch_cannot_double_count(book):
    store = Store()
    ingest_batch(store, book, EXAMPLE / "usage" / "batch-2027-03")
    with pytest.raises(Exception):  # batch id is a primary key
        ingest_batch(store, book, EXAMPLE / "usage" / "batch-2027-03")
    assert len(store.all_events()) == 5


def test_incomplete_batch_detected(book):
    store = Store()
    run_period(book, store, "2027-03")
    r = ingest_batch(store, book, EXAMPLE / "usage" / "batch-2027-04")
    assert not r.complete and r.late == 1


def test_invalid_events_rejected(book, tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"batch_id": "b", "count": 2, "quantity_sum": 5}))
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"event_id": "x1", "customer": "NOPE", "meter": "api_tokens", "quantity": 5, "timestamp": "2027-03-01T00:00:00Z"}) + "\n" +
        json.dumps({"event_id": "x2", "customer": "C-ACME", "meter": "api_tokens", "quantity": -1, "timestamp": "2027-03-01T00:00:00Z"}) + "\n")
    r = ingest_batch(Store(), book, tmp_path)
    assert len(r.rejected) == 2 and r.accepted == 0


# --- rating -------------------------------------------------------------------

@pytest.mark.parametrize("qty, expected", [(0, "0"), (100, "300"), (101, "302.5"), (150, "425"), (1200, "2950"), (1500, "3550")])
def test_graduated_rating_and_independent_rerate_agree(book, qty, expected):
    api = book.products["API"]
    assert rate_usage(api, D(qty)) == D(expected) == rerate_independently(api, D(qty))


# --- billing --------------------------------------------------------------------

def test_march_invoices(billed):
    _, march, _ = billed
    acme = march["K-ACME"]
    assert lines(acme, "subscription")[0]["amount"] == "7200.00"          # 20 x 30 x 12, annual in advance
    assert lines(acme, "usage")[0]["amount"] == "425.00"
    assert acme["tax"] == "676.72" and acme["total"] == "8301.72"         # NY 8.875% per line
    globex = march["K-GLOBEX"]
    assert lines(globex, "credit_applied")[0]["amount"] == "-2950.00"     # usage fully covered by commit
    assert globex["subtotal"] == "5500.00"                                # commit + support, usage nets to 0


def test_commit_runs_out_then_overage(billed):
    _, _, april = billed
    globex = april["K-GLOBEX"]
    assert lines(globex, "usage")[0]["amount"] == "2550.00"
    assert lines(globex, "credit_applied")[0]["amount"] == "-2050.00"     # only what was left
    assert globex["subtotal"] == "1000.00"                                # support 500 + overage 500


def test_late_event_billed_next_period_not_by_editing_march(billed):
    store, march, april = billed
    assert lines(april["K-ACME"], "usage")[0]["quantity"] == "50"
    assert "prior-period" in lines(april["K-ACME"], "usage")[0]["description"]
    assert ctl.c04_invoice_immutability(store=store).passed


def test_exempt_customer_has_no_tax_and_cites_certificate(billed):
    _, march, _ = billed
    line = march["K-UMBRELLA"]["lines"][0]
    assert line["tax"] == "0.00" and "EX-2027-0042" in line["tax_note"]


def test_period_cannot_be_billed_twice(book, billed):
    store, _, _ = billed
    with pytest.raises(BillingError):
        run_billing(book, store, "2027-04", RateTableProvider(book.tax_rates))


def test_unknown_jurisdiction_fails_closed(book):
    rates = {k: v for k, v in book.tax_rates.items() if k != "US-TX"}
    store = Store()
    ingest_batch(store, book, EXAMPLE / "usage" / "batch-2027-03")
    with pytest.raises(TaxError):
        run_billing(book, store, "2027-03", RateTableProvider(rates))
    assert store.invoices() == []                                        # nothing half-written


def test_book_validation(tmp_path):
    for name in ("catalog.yaml", "tax_rates.yaml"):
        (tmp_path / name).write_text((EXAMPLE / name).read_text())
    (tmp_path / "contracts.yaml").write_text((EXAMPLE / "contracts.yaml").read_text().replace("start: 2027-03-01", "start: 2027-03-15", 1))
    with pytest.raises(BookError):
        load_book(tmp_path)


# --- revenue ------------------------------------------------------------------

def test_allocation_sums_exactly():
    parts = allocate_by_days(D("7200.00"), date(2027, 3, 1), date(2028, 3, 1))
    assert len(parts) == 12 and sum(parts.values()) == D("7200.00")
    assert parts["2027-03"] == D("609.84")                               # 31 of 366 days


def test_revenue_by_period(book, billed):
    store, _, _ = billed
    rev = schedules(book, store.invoices(), "2027-04")
    assert rev["2027-03"].usage == D("3675.00")                          # 425 + 2950 + 300
    assert rev["2027-04"].breakage == D("700.00")                         # Initech used 300 of 1000
    assert rev["2027-04"].subscription == D("1390.16")                    # 590.16 Acme + 300 Umbrella + 500 support


def test_deferred_rollforward(book, billed):
    store, _, _ = billed
    rf = roll_forward(book, store.invoices(), "2027-04")
    assert [x.ending for x in rf] == [D("9340.16"), D("6000.00")]
    assert rf[1].beginning == rf[0].ending


def test_journal_balances_and_ties(book, billed):
    store, _, _ = billed
    entries = journal(book, store.invoices(), "2027-04")
    assert all(e.balanced for e in entries)
    tb = trial_balance(entries, "2027-04")
    assert sum(tb.values()) == 0
    assert -tb[DEFERRED] == D("6000.00")
    assert tb[AR] == sum(D(i["total"]) for i in store.invoices())
    revenue = sum(r.revenue for r in schedules(book, store.invoices(), "2027-04").values())
    assert -tb[REVENUE] == revenue


# --- controls -----------------------------------------------------------------

def test_march_controls_all_pass(book):
    store = Store()
    run_period(book, store, "2027-03")
    results = ctl.run_controls(store, book, "2027-03", EXAMPLE / "changes.yaml")
    assert [r.id for r in results if not r.passed] == []


def test_april_controls_catch_planted_issues(book, billed):
    store, _, _ = billed
    results = {r.id: r for r in ctl.run_controls(store, book, "2027-04", EXAMPLE / "changes.yaml")}
    assert {k for k, r in results.items() if not r.passed} == {"C-01", "C-08"}
    assert "carol" in results["C-08"].exceptions[0]


def test_tampered_invoice_detected(book, billed):
    store, _, _ = billed
    store.db.execute("UPDATE invoices SET body = replace(body, '8301.72', '1.00') WHERE invoice_id = 'INV-2027-03-K-ACME'")
    assert not ctl.c04_invoice_immutability(store=store).passed


def test_misrated_line_detected(book, billed):
    store, _, _ = billed
    store.db.execute("UPDATE invoices SET body = replace(body, '\"425.00\"', '\"420.00\"') WHERE invoice_id = 'INV-2027-03-K-ACME'")
    assert not ctl.c03_rating_accuracy(store=store, book=book, period="2027-03").passed


def test_evidence_pack(book, billed, tmp_path):
    store, _, _ = billed
    out = ctl.evidence_pack(ctl.run_controls(store, book, "2027-04", EXAMPLE / "changes.yaml"), "2027-04", tmp_path)
    data = json.loads((out / "evidence.json").read_text())
    assert len(data["controls"]) == 8 and (out / "evidence.sha256").exists()


# --- Stripe (fake module; nothing leaves the machine) --------------------------

class FakeStripe:
    def __init__(self):
        self.created = {}
        self.meter_events = []
        fake = self

        class Resource:
            def __init__(self, kind):
                self.kind = kind

            def create(self, idempotency_key=None, **params):
                obj = SimpleNamespace(id=f"{self.kind}_{len(fake.created)}", **params)
                fake.created[obj.id] = obj
                return obj

            def retrieve(self, id, expand=None):
                return fake.created[id]

        class MeterEvents:
            def create(self, **params):
                fake.meter_events.append(params)

        class Meters(Resource):
            def list_event_summaries(self, meter_id, customer, start_time, end_time):
                meter = fake.created[meter_id]
                total = sum(Decimal(e["payload"]["value"]) for e in fake.meter_events
                            if e["event_name"] == meter.event_name and e["payload"]["stripe_customer_id"] == customer)
                return SimpleNamespace(data=[{"aggregated_value": float(total)}])

        self.Product, self.Price, self.Customer = Resource("prod"), Resource("price"), Resource("cus")
        self.billing = SimpleNamespace(Meter=Meters("mtr"), MeterEvent=MeterEvents())


@pytest.mark.parametrize("key", [None, "", "sk_live_abc", "rk_live_abc", "pk_test_abc"])
def test_live_or_wrong_keys_refused(key):
    with pytest.raises(LiveKeyError):
        require_test_key(key)


def test_test_key_accepted():
    assert require_test_key("sk_test_123") == "sk_test_123"


def test_price_params_match_stripe_shapes(book):
    usage = price_params(book.products["API"], "month", "mtr_1")
    assert usage["billing_scheme"] == "tiered" and usage["tiers_mode"] == "graduated"
    assert usage["tiers"][-1] == {"up_to": "inf", "unit_amount_decimal": "200"}
    assert usage["recurring"] == {"interval": "month", "usage_type": "metered", "meter": "mtr_1"}
    seats = price_params(book.products["SEATS"], "year", None)
    assert seats["unit_amount_decimal"] == "36000"                       # 30 x 12 months, in cents
    assert price_params(book.products["SUPPORT"], "month", None)["unit_amount_decimal"] == "50000"


def test_stripe_catalog_and_usage_parity(book, billed):
    store, _, _ = billed
    stripe = FakeStripe()
    ids = sync_catalog(stripe, book)
    assert catalog_parity(stripe, book, ids) == []
    sent = push_usage(stripe, book, store, ids, "2027-03-01", "2027-05-01")
    assert sent == 8
    assert usage_parity(stripe, book, store, ids, "2027-03-01T00:00:00Z", "2027-05-01T00:00:00Z") == []
    stripe.meter_events.pop()                                            # Stripe lost one event
    assert usage_parity(stripe, book, store, ids, "2027-03-01T00:00:00Z", "2027-05-01T00:00:00Z")


def test_stripe_price_drift_detected(book):
    stripe = FakeStripe()
    ids = sync_catalog(stripe, book)
    stripe.created[ids["SUPPORT"]["price"]].unit_amount_decimal = "45000"
    assert any("SUPPORT" in p for p in catalog_parity(stripe, book, ids))
