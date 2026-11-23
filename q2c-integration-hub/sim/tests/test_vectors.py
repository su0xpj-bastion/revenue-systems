"""The Python mirror must agree with vectors/sync-vectors.json, the same file the Apex tests run."""
import json
import random
import unittest
from pathlib import Path

from q2c_sim import rules

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "vectors" / "sync-vectors.json").read_text("utf-8"))


class VectorTests(unittest.TestCase):
    def test_retry(self):
        for v in VECTORS["retry"]:
            with self.subTest(v["name"]):
                self.assertEqual(v["expect"], rules.classify(v["status"], v["timedOut"], v["attempts"], v["max"]).value)

    def test_backoff(self):
        rng = random.Random(0)
        for v in VECTORS["backoff"]:
            with self.subTest(attempts=v["attempts"]):
                self.assertEqual(v["baseSeconds"], rules.base_backoff_seconds(v["attempts"]))
                j = rules.jittered_backoff_seconds(v["attempts"], rng)
                self.assertTrue(v["baseSeconds"] // 2 <= j <= v["baseSeconds"])

    def test_transitions(self):
        for v in VECTORS["transitions"]:
            with self.subTest(f"{v['from']}->{v['to']}"):
                self.assertEqual(v["ok"], rules.can_transition(v["from"], v["to"]))

    def test_outbound_routes(self):
        for v in VECTORS["outbound"]:
            with self.subTest(v["status"]):
                self.assertEqual([tuple(t) for t in v["targets"]], rules.outbound_for(v["status"]))

    def test_keys_and_inbound(self):
        for v in VECTORS["keys"]:
            self.assertEqual(v["expect"], rules.outbound_key(v["target"], v["operation"], v["recordId"], v["version"]))
        for v in VECTORS["inbound"]:
            self.assertEqual(v["to"], rules.status_for_clm_event(v["type"]))
        self.assertIsNone(rules.status_for_clm_event("agreement.commented"))


if __name__ == "__main__":
    unittest.main()
