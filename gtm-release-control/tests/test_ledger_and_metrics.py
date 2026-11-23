import json

from coverage_gate import check
from evidence.ledger import GENESIS, append, head_hash, read_entries, verify
from pipeline_metrics import compute


def test_chain_links_and_verifies(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    first = append(ledger, "deploy", {"sha": "a"}, ts=1)
    second = append(ledger, "deploy", {"sha": "b"}, ts=2)
    assert first["prev_hash"] == GENESIS
    assert second["prev_hash"] == first["hash"]
    assert verify(ledger) == []
    assert head_hash(ledger) == second["hash"]


def test_edit_is_detected(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    append(ledger, "deploy", {"sha": "a", "approvers": ["alice"]}, ts=1)
    append(ledger, "deploy", {"sha": "b"}, ts=2)
    lines = ledger.read_text().splitlines()
    tampered = json.loads(lines[0])
    tampered["data"]["approvers"] = ["mallory"]
    lines[0] = json.dumps(tampered, sort_keys=True)
    ledger.write_text("\n".join(lines) + "\n")
    errors = verify(ledger)
    assert any("entry 0" in e and "edited" in e for e in errors)


def test_deletion_is_detected(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    for i in range(3):
        append(ledger, "deploy", {"sha": str(i)}, ts=i)
    lines = ledger.read_text().splitlines()
    ledger.write_text(lines[0] + "\n" + lines[2] + "\n")
    assert verify(ledger)


def test_empty_ledger_is_valid(tmp_path):
    assert verify(tmp_path / "missing.jsonl") == []


def test_metrics_from_ledger(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    opened = "2026-11-01T00:00:00Z"
    base = 1793491200  # same instant as `opened`, in epoch seconds
    append(ledger, "deploy", {"sha": "a", "lane": "agentic", "pr_opened_at": opened,
                              "classification_reasons": []}, ts=base + 2 * 3600)
    append(ledger, "deploy", {"sha": "b", "lane": "human_in_loop", "pr_opened_at": opened,
                              "classification_reasons": ["x/y.bin: no rule matched → ai_assisted (policy gap)"]},
           ts=base + 10 * 3600)
    append(ledger, "rollback", {"good_sha": "a", "bad_sha": "b"}, ts=base + 11 * 3600)

    m = compute(read_entries(ledger))
    assert m["deploys"] == 2
    assert m["lead_time_hours_median"] == 6.0
    assert m["change_failure_rate"] == 0.5
    assert m["lane_share"] == {"agentic": 0.5, "human_in_loop": 0.5}
    assert m["policy_gaps"] == {"x/y.bin": 1}


def test_coverage_gate():
    passing = {"result": {"summary": {"outcome": "Passed", "orgWideCoverage": "91%"}}}
    assert check(passing, 85) == []
    low = {"result": {"summary": {"outcome": "Passed", "orgWideCoverage": "80%"}}}
    assert any("below" in p for p in check(low, 85))
    failed = {"result": {"summary": {"outcome": "Failed", "orgWideCoverage": "95%", "failing": 2}}}
    assert any("outcome" in p for p in check(failed, 85))
    assert check({}, 85)
