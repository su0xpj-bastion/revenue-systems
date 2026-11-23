"""Randomised scenarios: concurrent edits, duplicate and reordered events, lost responses, outages."""
from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal

from . import rules
from .world import Clock, FakeBilling, FakeClm, Faults, IllegalTransition, Salesforce, Transport

PRODUCTS = ["SEATS", "API", "SUPPORT", "STORAGE"]


@dataclass
class Result:
    sf: Salesforce
    billing: FakeBilling
    clm: FakeClm
    transport: Transport
    illegal_rejected: int
    dead_before_operator: int
    inbound_outcomes: dict


def random_lines(rng: random.Random) -> dict[str, tuple[Decimal, Decimal]]:
    picks = rng.sample(PRODUCTS, rng.randint(1, 3))
    return {p: (Decimal(rng.randint(1, 50)), Decimal(rng.choice([10, 12, 99, 500]))) for p in picks}


def drain(sf: Salesforce, transport: Transport, clm: FakeClm, *, dup: float, shuffle: bool, max_rounds: int = 500) -> None:
    for _ in range(max_rounds):
        sf.deliver_events(dup, shuffle)
        clm.flush_webhooks(sf, dup, shuffle)
        sf.deliver_events(dup, shuffle)
        sf.dispatch(transport)
        nxt = sf.next_due_at()
        if nxt is None and not sf.event_bus and not clm.pending_webhooks:
            return
        if nxt is not None and nxt > sf.clock.now:
            sf.clock.advance(nxt - sf.clock.now)
    raise AssertionError("outbox did not drain")


def run(seed: int, *, contracts: int = 6, ops: int = 60, dup: float = 0.3, shuffle: bool = True,
        faults: Faults | None = None, max_attempts: int = 8) -> Result:
    rng = random.Random(seed)
    clock = Clock()
    sf = Salesforce(clock, rng, max_attempts=max_attempts, batch_size=rng.choice([1, 3, 50]))
    faults = faults or Faults(p_503=0.2, p_429=0.05, p_timeout_before_apply=0.05, p_timeout_after_apply=0.1,
                              outage_until=rng.choice([-1, 600, 3600]))
    billing = FakeBilling(clock, rng, faults)
    clm = FakeClm(rng)
    transport = Transport(billing, clm)
    ids = [sf.create_contract(random_lines(rng)).id for _ in range(contracts)]

    illegal = 0
    inbound: dict = {}
    for _ in range(ops):
        cid = rng.choice(ids)
        c = sf.contracts[cid]
        roll = rng.random()
        try:
            if roll < 0.35:
                lines = dict(c.lines)
                code = rng.choice(PRODUCTS)
                if code in lines and rng.random() < 0.3 and len(lines) > 1:
                    del lines[code]
                else:
                    lines[code] = (Decimal(rng.randint(1, 50)), Decimal(rng.choice([10, 12, 99, 500])))
                sf.save(cid, lines=lines)
            elif roll < 0.75:
                options = sorted(rules.NEXT[c.status])
                if options:
                    # Cancellation is terminal; keep it rare so most contracts get billed.
                    weights = [0.15 if o == rules.CANCELLED else 1.0 for o in options]
                    sf.save(cid, status=rng.choices(options, weights)[0])
            else:
                sf.save(cid, status=rng.choice([rules.ACTIVE, rules.DRAFT, rules.SIGNED]))
        except IllegalTransition:
            illegal += 1
        if rng.random() < 0.5:
            sf.deliver_events(dup, shuffle)
        if rng.random() < 0.4:
            for k, v in clm.flush_webhooks(sf, dup, shuffle).items():
                inbound[k] = inbound.get(k, 0) + v
        if rng.random() < 0.5:
            sf.dispatch(transport)
        clock.advance(rng.choice([1, 30, 120, 900]))

    # Outage and random failures end; everything still queued must now go through.
    faults.outage_until = -1
    faults.p_503 = faults.p_429 = faults.p_timeout_before_apply = faults.p_timeout_after_apply = 0.0
    drain(sf, transport, clm, dup=dup, shuffle=shuffle)
    dead = sum(1 for m in sf.outbox.values() if m.direction == "Outbound" and m.status == "Dead")
    if dead:
        sf.operator_retry_dead()  # the runbook step
        drain(sf, transport, clm, dup=dup, shuffle=shuffle)
    return Result(sf, billing, clm, transport, illegal, dead, inbound)
