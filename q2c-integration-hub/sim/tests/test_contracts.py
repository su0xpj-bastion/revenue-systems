"""Every payload the system builds must validate against the published data contracts."""
import json
import random
import unittest
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from q2c_sim import rules
from q2c_sim.chaos import run

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


def load(name):
    return json.loads((CONTRACTS / name).read_text("utf-8"))


SCHEMAS = {s["$id"]: s for s in (load(p.name) for p in CONTRACTS.glob("*.schema.json"))}
REGISTRY = Registry().with_resources((sid, Resource.from_contents(s)) for sid, s in SCHEMAS.items())


def validator(schema_id):
    return Draft202012Validator(SCHEMAS[schema_id], registry=REGISTRY)


class ContractTests(unittest.TestCase):
    def test_schemas_are_valid(self):
        for s in SCHEMAS.values():
            Draft202012Validator.check_schema(s)

    def test_outbound_payloads_validate(self):
        checked = 0
        for seed in range(30):
            r = run(seed, ops=30)
            for m in r.sf.outbox.values():
                if m.direction != "Outbound":
                    continue
                errors = list(validator(m.payload["schema"]).iter_errors(m.payload))
                self.assertEqual([], [e.message for e in errors], m.key)
                checked += 1
        self.assertGreater(checked, 100)

    def test_billing_snapshot_and_clm_event_examples(self):
        snapshot = {"contractId": "a01000000000000001", "version": 3, "status": "active",
                    "lines": [{"lineKey": "a01000000000000001:SEATS", "productCode": "SEATS", "quantity": 10, "unitPrice": 12}]}
        self.assertEqual([], list(validator("q2c.billing-contract.v1").iter_errors(snapshot)))
        evt = {"eventId": "evt_1", "type": "agreement.signed", "externalReference": "a01000000000000001", "agreementVersion": 2}
        self.assertEqual([], list(validator("q2c.clm-event.v1").iter_errors(evt)))
        bad = dict(evt, agreementVersion=0)
        self.assertNotEqual([], list(validator("q2c.clm-event.v1").iter_errors(bad)))

    def test_contract_rejects_draft_status(self):
        sf_payload = {"schema": "q2c.contract.v1", "operation": "upsert_contract", "contractId": "a01000000000000001",
                      "version": 1, "status": "Draft", "lines": []}
        self.assertNotEqual([], list(validator("q2c.contract.v1").iter_errors(sf_payload)))


if __name__ == "__main__":
    unittest.main()
