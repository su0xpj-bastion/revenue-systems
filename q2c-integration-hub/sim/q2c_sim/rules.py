"""Python mirror of the pure Apex rules (RetryPolicy, ContractStateMachine, IdempotencyKeys).

Both implementations run vectors/sync-vectors.json. The simulator is built on these functions, so a
chaos test that passes here is testing the same decisions the Apex code makes.
"""
from __future__ import annotations

import random
from enum import Enum

BASE_SECONDS = 30
CAP_SECONDS = 3600
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class Decision(str, Enum):
    ACK = "ACK"
    RETRY = "RETRY"
    DEAD = "DEAD"
    SUPERSEDED = "SUPERSEDED"


def classify(status: int | None, timed_out: bool, attempts: int, max_attempts: int) -> Decision:
    transient = timed_out or not status or status in RETRYABLE_STATUS
    if not transient:
        if 200 <= status < 300:
            return Decision.ACK
        if status == 409:
            return Decision.SUPERSEDED
        return Decision.DEAD
    return Decision.DEAD if attempts >= max_attempts else Decision.RETRY


def base_backoff_seconds(attempts: int) -> int:
    n = max(attempts or 1, 1)
    if n > 8:
        return CAP_SECONDS
    return min(BASE_SECONDS * 2 ** (n - 1), CAP_SECONDS)


def jittered_backoff_seconds(attempts: int, rng: random.Random) -> int:
    base = base_backoff_seconds(attempts)
    half = base // 2
    return half + rng.randint(0, half)


DRAFT, OUT_FOR_SIGNATURE, SIGNED, ACTIVE, CANCELLED = "Draft", "Out_For_Signature", "Signed", "Active", "Cancelled"

NEXT = {
    DRAFT: {OUT_FOR_SIGNATURE, CANCELLED},
    OUT_FOR_SIGNATURE: {DRAFT, SIGNED, CANCELLED},
    SIGNED: {ACTIVE, CANCELLED},
    ACTIVE: {CANCELLED},
    CANCELLED: set(),
}

CLM_EVENT_TO_STATUS = {
    "agreement.sent": OUT_FOR_SIGNATURE,
    "agreement.signed": SIGNED,
    "agreement.voided": CANCELLED,
}


def can_transition(frm: str, to: str) -> bool:
    return frm == to or to in NEXT.get(frm, set())


def status_for_clm_event(event_type: str) -> str | None:
    return CLM_EVENT_TO_STATUS.get(event_type)


def outbound_for(status: str) -> list[tuple[str, str]]:
    if status == OUT_FOR_SIGNATURE:
        return [("CLM", "upsert_agreement")]
    if status in (SIGNED, ACTIVE):
        return [("Billing", "upsert_contract")]
    if status == CANCELLED:
        return [("Billing", "cancel_contract"), ("CLM", "void_agreement")]
    return []


def outbound_key(target: str, operation: str, record_id: str, version: int) -> str:
    return f"{target.lower()}:{operation}:{record_id}:v{int(version)}"


def repair_key(key: str, run_id: str) -> str:
    return f"{key}:repair:{run_id}"


def inbound_key(source: str, event_id: str) -> str:
    return f"{source}-in:{event_id}"


def expected_billing_status(sf_status: str) -> str | None:
    if sf_status in (SIGNED, ACTIVE):
        return "active"
    if sf_status == CANCELLED:
        return "cancelled"
    return None
