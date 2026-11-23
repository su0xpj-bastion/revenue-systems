"""In-memory model of the Salesforce side, a fake Billing system and a fake CLM.

It follows the Apex design step for step (trigger version bumps, at-least-once Platform Events,
outbox with unique keys, dispatcher with supersede + retry, webhook dedupe + stale check,
reconciliation with repair) so the chaos tests can check the *design* under conditions an Apex
unit test can't produce: duplicate and reordered events, lost responses, outages, concurrent edits.
"""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from . import rules
from .recon import Drift, Line, compare


class IllegalTransition(Exception):
    pass


@dataclass
class Contract:
    id: str
    status: str = rules.DRAFT
    version: int = 1
    lines: dict[str, tuple[Decimal, Decimal]] = field(default_factory=dict)  # productCode -> (qty, price)
    billing_account_id: str = "ba_1"
    last_synced_version: int | None = None
    clm_version: int = 0
    synced_history: list[int] = field(default_factory=list)

    def line_key(self, product_code: str) -> str:
        return f"{self.id}:{product_code}"


@dataclass
class Message:
    key: str
    direction: str
    target: str
    operation: str
    record_id: str
    version: int
    payload: dict
    status: str = "Pending"
    attempts: int = 0  # reset by an operator retry
    sends: int = 0  # lifetime, never reset
    next_attempt_at: float = 0.0
    last_status: int | None = None
    last_error: str | None = None


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def advance(self, seconds: float) -> None:
        self.now += seconds


# --------------------------------------------------------------------------------------------
# Salesforce
# --------------------------------------------------------------------------------------------
class Salesforce:
    def __init__(self, clock: Clock, rng: random.Random, max_attempts: int = 8, batch_size: int = 50) -> None:
        self.clock = clock
        self.rng = rng
        self.max_attempts = max_attempts
        self.batch_size = batch_size
        self.contracts: dict[str, Contract] = {}
        self.outbox: dict[str, Message] = {}
        self.event_bus: list[tuple[str, int]] = []  # (recordId, version) published after commit
        self.drifts: list[tuple[str, Drift]] = []
        self.outbound_enabled = True
        self._seq = 0

    # ---- trigger behaviour -------------------------------------------------------------------
    def create_contract(self, lines: dict[str, tuple[Decimal, Decimal]]) -> Contract:
        self._seq += 1
        c = Contract(id=f"a01{self._seq:015d}", lines=dict(lines))
        self.contracts[c.id] = c
        self._publish(c)
        return c

    def save(self, contract_id: str, *, status: str | None = None, lines: dict | None = None) -> Contract:
        c = self.contracts[contract_id]
        new_status = c.status if status is None else status
        if not rules.can_transition(c.status, new_status):
            raise IllegalTransition(f"{c.status} -> {new_status}")
        changed = new_status != c.status or (lines is not None and lines != c.lines)
        c.status = new_status
        if lines is not None:
            c.lines = dict(lines)
        if changed:
            c.version += 1
            self._publish(c)
        return c

    def _publish(self, c: Contract) -> None:
        self.event_bus.append((c.id, c.version))

    # ---- Platform Event subscriber (at-least-once, any order) --------------------------------
    def deliver_events(self, duplicate_rate: float = 0.0, shuffle: bool = False) -> int:
        batch = list(self.event_bus)
        self.event_bus.clear()
        for ev in list(batch):
            if self.rng.random() < duplicate_rate:
                batch.append(ev)
        if shuffle:
            self.rng.shuffle(batch)
        inserted = 0
        for record_id, _event_version in batch:
            inserted += self.enqueue_contracts({record_id})
        # Late redelivery: some events come back in a later batch, after their message may already
        # have been sent and acked (subscriber retry, replay from a stored replayId).
        self.event_bus.extend(ev for ev in batch if self.rng.random() < duplicate_rate / 3)
        return inserted

    def enqueue_contracts(self, ids: set[str], repair_run: str | None = None) -> int:
        inserted = 0
        for cid in sorted(ids):
            c = self.contracts[cid]
            for target, operation in rules.outbound_for(c.status):
                key = rules.outbound_key(target, operation, c.id, c.version)
                if repair_run:
                    key = rules.repair_key(key, repair_run)
                if key in self.outbox:  # unique index: DUPLICATE_VALUE = already queued
                    continue
                self.outbox[key] = Message(
                    key=key, direction="Outbound", target=target, operation=operation, record_id=c.id,
                    version=c.version, payload=self.payload(c, target, operation), next_attempt_at=self.clock.now,
                )
                inserted += 1
        return inserted

    def payload(self, c: Contract, target: str, operation: str) -> dict:
        lines = [
            {"lineKey": c.line_key(code), "productCode": code, "quantity": float(q), "unitPrice": float(p)}
            for code, (q, p) in sorted(c.lines.items(), key=lambda kv: c.line_key(kv[0]))
        ]
        body = {"operation": operation, "contractId": c.id, "version": c.version, "status": c.status, "lines": lines}
        if target == "Billing":
            body.update(schema="q2c.contract.v1", billingAccountId=c.billing_account_id,
                        startDate="2026-01-01", endDate="2026-12-31")
        else:
            body.update(schema="q2c.agreement.v1", externalReference=c.id, title=f"Contract {c.id}")
        return body

    # ---- OutboxDispatcher --------------------------------------------------------------------
    def dispatch(self, transport: "Transport") -> dict[str, int]:
        summary = Counter()
        if not self.outbound_enabled:
            return summary
        due = [m for m in self.outbox.values()
               if m.direction == "Outbound" and m.status in ("Pending", "Retrying") and m.next_attempt_at <= self.clock.now]
        self.rng.shuffle(due)  # SOQL without ORDER BY: no ordering guarantee
        due = due[: self.batch_size + 1]
        newest: dict[tuple[str, str], Message] = {}
        for m in due:
            stream = (m.target, m.record_id)
            cur = newest.get(stream)
            if cur is None or m.version > cur.version:
                if cur is not None:
                    cur.status = "Superseded"
                    summary["superseded"] += 1
                newest[stream] = m
            else:
                m.status = "Superseded"
                summary["superseded"] += 1

        for m in list(newest.values())[: self.batch_size]:
            status, timed_out = transport.send(m)
            m.attempts += 1
            m.sends += 1
            m.last_status = status
            d = rules.classify(status, timed_out, m.attempts, self.max_attempts)
            if d is rules.Decision.ACK:
                m.status = "Acked"
                if m.target == "Billing":
                    c = self.contracts[m.record_id]
                    if c.last_synced_version is None or m.version > c.last_synced_version:
                        c.last_synced_version = m.version
                        c.synced_history.append(m.version)
            elif d is rules.Decision.SUPERSEDED:
                m.status = "Superseded"
            elif d is rules.Decision.RETRY:
                m.status = "Retrying"
                m.next_attempt_at = self.clock.now + rules.jittered_backoff_seconds(m.attempts, self.rng)
            else:
                m.status = "Dead"
            summary[m.status.lower()] += 1
        return summary

    def next_due_at(self) -> float | None:
        times = [m.next_attempt_at for m in self.outbox.values() if m.status in ("Pending", "Retrying")]
        return min(times) if times else None

    def operator_retry_dead(self) -> int:
        n = 0
        for m in self.outbox.values():
            if m.direction == "Outbound" and m.status == "Dead":
                m.status, m.attempts, m.next_attempt_at = "Pending", 0, self.clock.now
                n += 1
        return n

    # ---- CLM webhook + InboundApplier ----------------------------------------------------------
    def receive_clm_event(self, event: dict) -> str:
        new_status = rules.status_for_clm_event(event["type"])
        if new_status is None:
            return "ignored_type"
        key = rules.inbound_key("clm", event["eventId"])
        if key in self.outbox:
            return "duplicate"
        msg = Message(key=key, direction="Inbound", target="CLM", operation=event["type"],
                      record_id=event["externalReference"], version=int(event["agreementVersion"]), payload=event)
        self.outbox[key] = msg
        self.apply_inbound(msg)
        return msg.status

    def apply_inbound(self, msg: Message) -> None:
        c = self.contracts.get(msg.record_id)
        new_status = rules.status_for_clm_event(msg.operation)
        if c is None:
            msg.status = "Parked"
        elif msg.version <= c.clm_version:
            msg.status = "Ignored_Stale"
        elif not rules.can_transition(c.status, new_status):
            msg.status = "Dead"
        else:
            self.save(c.id, status=new_status)
            c.clm_version = msg.version
            msg.status = "Applied"

    # ---- ReconciliationJob ---------------------------------------------------------------------
    def reconcile(self, billing: "FakeBilling", run_id: str, repair: bool = True) -> list[tuple[str, Drift]]:
        found: list[tuple[str, Drift]] = []
        to_repair: set[str] = set()
        for c in self.contracts.values():
            if rules.expected_billing_status(c.status) is None or c.last_synced_version != c.version:
                continue
            snap = billing.get(c.id)
            sf_lines = [Line(c.line_key(code), code, q, p) for code, (q, p) in c.lines.items()]
            if snap is None:
                drifts = compare(c.status, sf_lines, None, None)
            else:
                b_lines = [Line(k, k.split(":", 1)[1], Decimal(str(q)), Decimal(str(p))) for k, (q, p) in snap["lines"].items()]
                drifts = compare(c.status, sf_lines, snap["status"], b_lines)
            for d in drifts:
                found.append((c.id, d))
                to_repair.add(c.id)
        self.drifts.extend(found)
        if repair and to_repair:
            self.enqueue_contracts(to_repair, repair_run=run_id)
        return found


# --------------------------------------------------------------------------------------------
# Fakes for the other systems
# --------------------------------------------------------------------------------------------
@dataclass
class Faults:
    p_503: float = 0.0
    p_429: float = 0.0
    p_timeout_before_apply: float = 0.0
    p_timeout_after_apply: float = 0.0  # applied, but the response is lost: the nasty one
    outage_until: float = -1.0


class FakeBilling:
    """Honours the q2c.contract.v1 contract: idempotency-key replay, version ordering (409)."""

    def __init__(self, clock: Clock, rng: random.Random, faults: Faults | None = None) -> None:
        self.clock = clock
        self.rng = rng
        self.faults = faults or Faults()
        self.contracts: dict[str, dict] = {}
        self.replay: dict[str, int] = {}
        self.effective_applies: Counter[str] = Counter()
        self.version_history: dict[str, list[int]] = {}

    def handle(self, m: Message) -> tuple[int, bool]:
        f = self.faults
        if self.clock.now < f.outage_until:
            return 503, False
        if m.key in self.replay:
            return self.replay[m.key], False
        r = self.rng.random()
        if r < f.p_503:
            return 503, False
        if r < f.p_503 + f.p_429:
            return 429, False
        if r < f.p_503 + f.p_429 + f.p_timeout_before_apply:
            return 0, True

        stored = self.contracts.get(m.record_id)
        if stored is not None and m.version < stored["version"]:
            self.replay[m.key] = 409
            return 409, False
        p = m.payload
        self.contracts[m.record_id] = {
            "version": m.version,
            "status": "cancelled" if m.operation == "cancel_contract" else "active",
            "lines": {ln["lineKey"]: (ln["quantity"], ln["unitPrice"]) for ln in p["lines"]},
        }
        self.version_history.setdefault(m.record_id, []).append(m.version)
        self.effective_applies[m.key] += 1
        self.replay[m.key] = 200
        if self.rng.random() < f.p_timeout_after_apply:
            return 0, True
        return 200, False

    def get(self, contract_id: str) -> dict | None:
        return self.contracts.get(contract_id)

    def tamper(self, contract_id: str, line_key: str, quantity: float) -> None:
        """Out-of-band change (someone edits Billing directly)."""
        self.contracts[contract_id]["lines"][line_key] = (quantity, self.contracts[contract_id]["lines"][line_key][1])


class FakeClm:
    """Accepts agreement upserts and voids, and later emits signature webhooks."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.agreement_version: Counter[str] = Counter()
        self.pending_webhooks: list[dict] = []
        self._event_seq = 0

    def handle(self, m: Message) -> tuple[int, bool]:
        self.agreement_version[m.record_id] += 1
        if m.operation == "upsert_agreement" and self.rng.random() < 0.7:
            self.agreement_version[m.record_id] += 1
            self._event_seq += 1
            self.pending_webhooks.append({
                "eventId": f"evt_{self._event_seq}", "type": "agreement.signed",
                "externalReference": m.record_id, "agreementId": f"agr_{m.record_id}",
                "agreementVersion": self.agreement_version[m.record_id],
            })
        return 200, False

    def flush_webhooks(self, sf: Salesforce, duplicate_rate: float, shuffle: bool) -> Counter[str]:
        batch = list(self.pending_webhooks)
        self.pending_webhooks.clear()
        batch += [e for e in list(batch) if self.rng.random() < duplicate_rate]
        if shuffle:
            self.rng.shuffle(batch)
        return Counter(sf.receive_clm_event(e) for e in batch)


class Transport:
    def __init__(self, billing: FakeBilling, clm: FakeClm) -> None:
        self.billing = billing
        self.clm = clm
        self.sent: list[str] = []

    def send(self, m: Message) -> tuple[int, bool]:
        self.sent.append(m.key)
        return (self.billing if m.target == "Billing" else self.clm).handle(m)
