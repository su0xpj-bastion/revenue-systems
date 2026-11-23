import random
import unittest
from decimal import Decimal

from q2c_sim import rules
from q2c_sim.world import Clock, Salesforce


def event(eid, typ, ref, version):
    return {"eventId": eid, "type": typ, "externalReference": ref, "agreementId": "agr_1", "agreementVersion": version}


class InboundTests(unittest.TestCase):
    def setUp(self):
        self.sf = Salesforce(Clock(), random.Random(1))
        self.c = self.sf.create_contract({"SEATS": (Decimal(1), Decimal(1))})
        self.sf.save(self.c.id, status=rules.OUT_FOR_SIGNATURE)

    def test_apply_then_duplicate(self):
        v = self.c.version
        self.assertEqual("Applied", self.sf.receive_clm_event(event("e1", "agreement.signed", self.c.id, 1)))
        self.assertEqual(rules.SIGNED, self.c.status)
        self.assertEqual(v + 1, self.c.version, "signing is a billing change, so it publishes")
        self.assertEqual("duplicate", self.sf.receive_clm_event(event("e1", "agreement.signed", self.c.id, 1)))

    def test_out_of_order_older_event_is_ignored(self):
        self.sf.receive_clm_event(event("e2", "agreement.signed", self.c.id, 2))
        self.assertEqual("Ignored_Stale", self.sf.receive_clm_event(event("e1", "agreement.sent", self.c.id, 1)))
        self.assertEqual(rules.SIGNED, self.c.status)

    def test_illegal_transition_is_dead(self):
        self.sf.save(self.c.id, status=rules.CANCELLED)
        self.assertEqual("Dead", self.sf.receive_clm_event(event("e3", "agreement.signed", self.c.id, 5)))
        self.assertEqual(rules.CANCELLED, self.c.status)

    def test_unknown_contract_is_parked(self):
        self.assertEqual("Parked", self.sf.receive_clm_event(event("e4", "agreement.signed", "a01999999999999999", 1)))

    def test_unknown_type_is_ignored(self):
        self.assertEqual("ignored_type", self.sf.receive_clm_event(event("e5", "agreement.commented", self.c.id, 1)))


if __name__ == "__main__":
    unittest.main()
