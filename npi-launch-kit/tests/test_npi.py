import copy
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from npi import catalog, migration, readiness, reconcile, scenarios
from npi.ai import draft_spec, propose_scenarios
from npi.lint import blocking, lint
from npi.pricing import QuoteLine, coterm_proration, invoice_schedule, tiered_amount
from npi.spec import Tier, parse_spec

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "insights-launch"
RAW = yaml.safe_load((EXAMPLE / "spec.yaml").read_text())
D = Decimal


def spec(mutate=None):
    data = copy.deepcopy(RAW)
    if mutate:
        mutate(data)
    return parse_spec(data)


def product(data, sku):
    return next(p for p in data["products"] if p["sku"] == sku)


def rules(launch):
    return {f.rule for f in lint(launch)}


# --- spec + lint -------------------------------------------------------------

def test_example_spec_is_clean():
    assert blocking(lint(spec())) == []


@pytest.mark.parametrize("mutate, rule", [
    (lambda d: product(d, "INS-TEAM").update(tax_code=None), "missing-tax-code"),
    (lambda d: product(d, "INS-TEAM").update(revenue=None), "missing-revenue-treatment"),
    (lambda d: product(d, "INS-TEAM").update(term_months=10, billing_frequency="quarterly"), "term-not-billable"),
    (lambda d: product(d, "INS-API").update(usage_source=None), "usage-no-source"),
    (lambda d: product(d, "INS-API")["tiers"][-1].update(up_to=5000), "last-tier-bounded"),
    (lambda d: product(d, "INS-API")["tiers"][1].update(up_to=50), "tier-bounds"),
    (lambda d: product(d, "INS-ENT").update(term_months=24), "ramp-term-mismatch"),
    (lambda d: product(d, "INS-ENT").update(usage_sku="INS-TEAM"), "commit-usage-sku"),
    (lambda d: d["bundles"][0]["optional"].append("NOPE"), "bundle-unknown-component"),
    (lambda d: d["approvals"].reverse(), "approval-bands-order"),
    (lambda d: d["retirements"][0].update(replacement="NOPE"), "retire-no-replacement"),
    (lambda d: d["retirements"][0].update(end_of_renewal="2027-01-01"), "retire-dates-order"),
    (lambda d: d.update(signoffs=["product"]), "missing-required-signoff"),
    (lambda d: d.update(open_questions=["Does unused commit roll over?"]), "open-question"),
    (lambda d: d["launch"].update(first_bill_run="2027-02-01"), "bill-run-before-launch"),
])
def test_blocking_rules(mutate, rule):
    launch = spec(mutate)
    assert rule in {f.rule for f in blocking(lint(launch))}


@pytest.mark.parametrize("mutate, rule", [
    (lambda d: product(d, "INS-ENT").update(overage_rate=1.50), "cheap-overage"),
    (lambda d: product(d, "INS-ENT").update(overage_rate=3.50), "overage-above-payg"),
    (lambda d: product(d, "INS-ENT")["ramp"][2].update(commit=50000), "down-ramp"),
    (lambda d: product(d, "INS-API")["tiers"][2].update(price=2.75), "price-rises-with-volume"),
    (lambda d: d["retirements"][0].update(end_of_sale="2027-01-01"), "retire-before-launch"),
])
def test_warning_rules(mutate, rule):
    findings = [f for f in lint(spec(mutate)) if f.rule == rule]
    assert findings and findings[0].severity == "warn"


def test_findings_name_who_to_push_back_to():
    launch = spec(lambda d: product(d, "INS-TEAM").update(tax_code=None))
    finding = next(f for f in lint(launch) if f.rule == "missing-tax-code")
    assert finding.push_back_to == "tax" and finding.sku == "INS-TEAM"


# --- pricing -----------------------------------------------------------------

TIERS = [Tier(D(100), D("3.00")), Tier(D(1000), D("2.50")), Tier(None, D("2.00"))]


@pytest.mark.parametrize("qty, graduated, volume", [
    (0, "0", "0"),
    (100, "300.00", "300.00"),
    (101, "302.50", "252.50"),
    (1500, "3550.00", "3000.00"),
])
def test_tiered_amount(qty, graduated, volume):
    assert tiered_amount(D(qty), TIERS, "graduated") == D(graduated)
    assert tiered_amount(D(qty), TIERS, "volume") == D(volume)


def test_annual_seat_billing_is_one_invoice_in_advance():
    invoices = invoice_schedule(spec(), [QuoteLine("INS-TEAM", D(10))], date(2027, 3, 1))
    assert [(i.period_start, i.amount) for i in invoices] == [(date(2027, 3, 1), D("3600.00"))]


def test_commit_exhaustion_splits_the_crossing_month():
    usage = {"INS-API": [D(3500)] * 12}
    invoices = invoice_schedule(spec(), [QuoteLine("INS-ENT")], date(2027, 3, 1), usage)
    overage = [i for i in invoices if i.kind == "overage"]
    assert overage[0].period_start == date(2027, 11, 1)
    assert overage[0].quantity == D(1500) and overage[0].amount == D("3375.00")
    assert len(overage) == 4


def test_coterm_proration_monthly_plus_daily():
    # 2 full months (Apr 15 → Jun 15) + 16 of 30 June days
    amount = coterm_proration(D(30), D(10), date(2027, 4, 15), date(2027, 7, 1))
    assert amount == D("760.00")


def test_example_scenarios_all_pass():
    results = scenarios.run_all(spec(), scenarios.load_scenarios(EXAMPLE / "scenarios.yaml"))
    assert [r.scenario.name for r in results if not r.passed] == []


def test_wrong_expectation_fails():
    s = scenarios.parse_scenarios({"scenarios": [{
        "name": "x", "start": "2027-03-01", "lines": [{"sku": "INS-TEAM", "quantity": 10}],
        "expect": {"total": 1}}]})[0]
    assert not scenarios.run(spec(), s).passed


# --- catalog -----------------------------------------------------------------

def test_catalog_tables():
    tables = catalog.build_catalog(spec())
    codes = {r["ProductCode"] for r in tables["Product2"]}
    assert {"INS-TEAM", "INS-API", "INS-ENT", "INS-SUPPORT-PREM", "INS-STARTER", "LEGACY-ANALYTICS"} <= codes
    tiers = tables["SBQQ__DiscountTier__c"]
    assert [(t["SBQQ__LowerBound__c"], t["SBQQ__UpperBound__c"]) for t in tiers] == [
        ("0", "100"), ("100", "1000"), ("1000", "")]
    assert tables["SBQQ__DiscountSchedule__c"][0]["SBQQ__Type__c"] == "Slab"
    assert tables["approval_rules"][-1]["approver"].startswith("reject")


def test_catalog_diff_against_live_export():
    changes = {c.sku: c for c in catalog.diff_catalog(spec(), catalog.read_csv(EXAMPLE / "current_catalog.csv"))}
    assert changes["INS-TEAM"].action == "ADD"
    assert changes["INS-SUPPORT-PREM"].action == "CHANGE" and "450.00 → 500.00" in changes["INS-SUPPORT-PREM"].detail
    assert changes["LEGACY-ANALYTICS"].action == "END_OF_SALE"


def test_write_tables(tmp_path):
    paths = catalog.write_tables(catalog.build_catalog(spec()), tmp_path)
    assert (tmp_path / "Product2.csv") in paths


# --- migration ---------------------------------------------------------------

def test_migration_plan_flags():
    rows = {r.account: r for r in migration.plan_migrations(
        spec(), catalog.read_csv(EXAMPLE / "subscriptions.csv"), date(2027, 3, 1))}
    assert set(rows) == {"ACME", "GLOBEX", "INITECH"}           # HOOLI is not on a retiring SKU
    assert rows["ACME"].uplift_pct == D("20.0") and any("CS outreach" in f for f in rows["ACME"].flags)
    assert any("below INS-TEAM minimum" in f for f in rows["GLOBEX"].flags)
    assert any("after end_of_renewal" in f for f in rows["INITECH"].flags)


def test_coterm_migration_nets_credit_and_charge():
    launch = spec(lambda d: d["retirements"][0].update(policy="migrate_now_coterm"))
    rows = migration.plan_migrations(launch, catalog.read_csv(EXAMPLE / "subscriptions.csv"), date(2027, 3, 1))
    acme = next(r for r in rows if r.account == "ACME")
    # 3 months (Mar 1 → Jun 1) x 20 seats x ($30 - $25)
    assert acme.amendment_net == D("300.00")


# --- readiness ---------------------------------------------------------------

def test_items_follow_the_spec():
    ids = {i.id for i in readiness.build_items(spec())}
    assert {"metering:INS-API", "tiers:INS-API", "contract:INS-ENT", "migration:LEGACY-ANALYTICS"} <= ids
    assert "metering:INS-TEAM" not in ids


def test_no_go_until_everything_done():
    launch = spec()
    done, signoffs = readiness.load_tracker(EXAMPLE / "tracker.yaml")
    go, reasons = readiness.go_no_go(launch, done, signoffs, date(2027, 2, 20))
    assert not go and any("missing sign-off: finance" in r for r in reasons)

    everything = {i.id for i in readiness.build_items(launch)}
    all_signed = {t: {"by": "x", "date": "2027-02-01"} for t in launch.signoffs}
    assert readiness.go_no_go(launch, everything, all_signed, date(2027, 2, 20))[0]


def test_report_marks_overdue():
    launch = spec()
    text = readiness.report(launch, set(), {}, date(2027, 2, 20))
    assert "NO-GO" in text and "OVERDUE" in text


# --- reconciliation ----------------------------------------------------------

def test_reconciliation_catches_every_planted_defect():
    results = {r.name: r for r in reconcile.run_controls(spec(), EXAMPLE / "post_launch")}
    failing = {name for name, r in results.items() if not r.passed}
    assert failing == {
        "quote_vs_order", "accepted_quote_without_order", "order_not_invoiced",
        "tax_code_mismatch", "finance_report_vs_billing", "retired_sku_on_new_business",
    }
    assert [row[0] for row in results["retired_sku_on_new_business"].rows] == ["Q-1005"]  # renewal Q-1006 allowed


# --- Claude (fake client; no network) ----------------------------------------

class FakeClient:
    def __init__(self, payload, stop_reason="end_turn"):
        self.calls = []
        response = SimpleNamespace(stop_reason=stop_reason,
                                   content=[SimpleNamespace(type="text", text=json.dumps(payload))])

        def create(**kwargs):
            self.calls.append(kwargs)
            return response

        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))


def test_draft_is_linted_like_any_spec():
    draft = copy.deepcopy(RAW)
    for d in ("launch_date", "first_bill_run"):
        draft["launch"][d] = str(draft["launch"][d])
    for r in draft["retirements"]:
        r["end_of_sale"], r["end_of_renewal"] = str(r["end_of_sale"]), str(r["end_of_renewal"])
    product(draft, "INS-ENT")["tax_code"] = None
    draft["open_questions"] = ["Can Enterprise commit be invoiced quarterly? (finance)"]
    client = FakeClient(draft)

    launch = parse_spec(draft_spec(client, "brief"))
    block_rules = {f.rule for f in blocking(lint(launch))}
    assert {"missing-tax-code", "open-question"} <= block_rules
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "Never invent" in call["system"]


def test_draft_refusal_raises():
    from npi.ai import DraftError
    with pytest.raises(DraftError):
        draft_spec(FakeClient({}, stop_reason="refusal"), "brief")


def test_proposed_scenarios_reshape_usage():
    client = FakeClient({"scenarios": [{
        "name": "edge", "why": "tier boundary", "start": "2027-03-01",
        "lines": [{"sku": "INS-API", "quantity": 1, "discount_pct": 0}],
        "usage": [{"sku": "INS-API", "monthly": [100, 101]}],
    }]})
    proposed = propose_scenarios(client, "spec", 1)
    assert proposed[0]["usage"] == {"INS-API": [100, 101]}
