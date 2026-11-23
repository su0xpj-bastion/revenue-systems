"""Invariants that must hold after any interleaving of edits, duplicate/reordered events and faults."""
import random
import unittest
from collections import Counter
from decimal import Decimal

from q2c_sim import rules
from q2c_sim.chaos import drain, run
from q2c_sim.world import Clock, FakeBilling, FakeClm, Faults, Salesforce, Transport

SEEDS = range(150)


def billing_lines(snapshot):
    return {k: (Decimal(str(q)).quantize(Decimal("0.01")), Decimal(str(p)).quantize(Decimal("0.01")))
            for k, (q, p) in snapshot["lines"].items()}


def sf_lines(c):
    return {c.line_key(code): (q.quantize(Decimal("0.01")), p.quantize(Decimal("0.01"))) for code, (q, p) in c.lines.items()}


class ChaosInvariants(unittest.TestCase):
    def test_billing_converges_to_salesforce(self):
        for seed in SEEDS:
            r = run(seed)
            for c in r.sf.contracts.values():
                expected = rules.expected_billing_status(c.status)
                snap = r.billing.get(c.id)
                with self.subTest(seed=seed, contract=c.id, status=c.status):
                    if expected is None:
                        # Draft / out-for-signature contracts can never have been signed: Billing never saw them.
                        self.assertIsNone(snap)
                        continue
                    self.assertIsNotNone(snap)
                    self.assertEqual(c.version, snap["version"])
                    self.assertEqual(expected, snap["status"])
                    if expected == "active":
                        self.assertEqual(sf_lines(c), billing_lines(snap))
                    self.assertEqual(c.version, c.last_synced_version)

    def test_each_key_takes_effect_at_most_once(self):
        for seed in SEEDS:
            r = run(seed)
            with self.subTest(seed=seed):
                self.assertTrue(all(n == 1 for n in r.billing.effective_applies.values()))
                # A key is only re-sent as a retry of the same message, never because it was queued twice.
                sends = Counter(r.transport.sent)
                for key, n in sends.items():
                    self.assertEqual(r.sf.outbox[key].sends, n, key)

    def test_versions_never_move_backwards(self):
        for seed in SEEDS:
            r = run(seed)
            with self.subTest(seed=seed):
                for history in r.billing.version_history.values():
                    self.assertEqual(history, sorted(history))
                for c in r.sf.contracts.values():
                    self.assertEqual(c.synced_history, sorted(set(c.synced_history)))
                    self.assertLessEqual(c.last_synced_version or 0, c.version)

    def test_no_drift_after_drain(self):
        for seed in SEEDS:
            r = run(seed)
            with self.subTest(seed=seed):
                self.assertEqual([], r.sf.reconcile(r.billing, "final", repair=False))

    def test_inbound_never_applies_stale_or_illegal(self):
        for seed in SEEDS:
            r = run(seed)
            for m in r.sf.outbox.values():
                if m.direction != "Inbound":
                    continue
                with self.subTest(seed=seed, key=m.key):
                    self.assertIn(m.status, {"Applied", "Ignored_Stale", "Dead", "Parked"})
            with self.subTest(seed=seed, check="dup"):
                keys = [m.key for m in r.sf.outbox.values() if m.direction == "Inbound"]
                self.assertEqual(len(keys), len(set(keys)))


class FailureModes(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(7)
        self.clock = Clock()
        self.sf = Salesforce(self.clock, self.rng, max_attempts=3)
        self.faults = Faults()
        self.billing = FakeBilling(self.clock, self.rng, self.faults)
        self.clm = FakeClm(self.rng)
        self.transport = Transport(self.billing, self.clm)

    def active_contract(self):
        c = self.sf.create_contract({"SEATS": (Decimal(10), Decimal(12))})
        for s in (rules.OUT_FOR_SIGNATURE, rules.SIGNED, rules.ACTIVE):
            self.sf.save(c.id, status=s)
        return c

    def test_long_outage_dead_letters_then_operator_retry_converges(self):
        c = self.active_contract()
        self.faults.outage_until = 10**9
        self.sf.deliver_events()
        for _ in range(10):
            self.sf.dispatch(self.transport)
            if self.sf.next_due_at() is not None:
                self.clock.advance(max(0, self.sf.next_due_at() - self.clock.now))
        dead = [m for m in self.sf.outbox.values() if m.status == "Dead"]
        self.assertEqual(1, len(dead))
        self.assertEqual(3, dead[0].attempts)
        self.assertIsNone(self.billing.get(c.id))
        self.faults.outage_until = -1
        self.assertEqual(1, self.sf.operator_retry_dead())
        drain(self.sf, self.transport, self.clm, dup=0, shuffle=False)
        self.assertEqual(c.version, self.billing.get(c.id)["version"])

    def test_lost_response_is_retried_and_replayed_not_reapplied(self):
        c = self.active_contract()
        self.faults.p_timeout_after_apply = 1.0
        self.sf.deliver_events()
        self.sf.dispatch(self.transport)
        msg = next(m for m in self.sf.outbox.values() if m.target == "Billing")
        self.assertEqual("Retrying", msg.status)
        self.assertEqual(c.version, self.billing.get(c.id)["version"], "Billing did apply it")
        self.faults.p_timeout_after_apply = 0.0
        self.clock.advance(3600)
        self.sf.dispatch(self.transport)
        self.assertEqual("Acked", msg.status)
        self.assertEqual(1, self.billing.effective_applies[msg.key])

    def test_kill_switch_queues_then_drains(self):
        c = self.active_contract()
        self.sf.outbound_enabled = False
        self.sf.deliver_events()
        self.sf.dispatch(self.transport)
        self.assertEqual([], self.transport.sent)
        self.sf.outbound_enabled = True
        drain(self.sf, self.transport, self.clm, dup=0, shuffle=False)
        self.assertEqual(c.version, self.billing.get(c.id)["version"])

    def test_late_old_version_gets_409_and_is_superseded(self):
        c = self.active_contract()
        self.sf.deliver_events()
        old = next(m for m in self.sf.outbox.values() if m.target == "Billing")
        self.faults.outage_until = self.clock.now + 1
        self.sf.dispatch(self.transport)  # old version -> 503, Retrying
        self.clock.advance(5)
        self.sf.save(c.id, lines={"SEATS": (Decimal(20), Decimal(12))})
        self.sf.deliver_events()
        newer = next(m for m in self.sf.outbox.values() if m.version == c.version)
        newer.next_attempt_at = self.clock.now
        old.next_attempt_at = 10**9  # not due yet
        self.sf.dispatch(self.transport)
        self.assertEqual("Acked", newer.status)
        old.next_attempt_at = self.clock.now
        self.sf.dispatch(self.transport)
        self.assertEqual("Superseded", old.status, "Billing said 409: it already holds a newer version")
        self.assertEqual(c.version, self.billing.get(c.id)["version"])

    def test_reconciliation_detects_tampering_and_repair_fixes_it(self):
        c = self.active_contract()
        drain(self.sf, self.transport, self.clm, dup=0, shuffle=False)
        self.billing.tamper(c.id, c.line_key("SEATS"), 7)
        drifts = self.sf.reconcile(self.billing, "recon-1")
        self.assertEqual(["Quantity_Mismatch"], [d.kind for _, d in drifts])
        repair = [m for m in self.sf.outbox.values() if ":repair:recon-1" in m.key]
        self.assertEqual(1, len(repair), "repair uses a fresh key so Billing re-applies instead of replaying")
        drain(self.sf, self.transport, self.clm, dup=0, shuffle=False)
        self.assertEqual([], self.sf.reconcile(self.billing, "recon-2"))


if __name__ == "__main__":
    unittest.main()
