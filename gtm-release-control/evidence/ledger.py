"""Append-only, hash-chained change ledger.

Each entry stores the SHA-256 of the previous entry, so editing or deleting any past entry
breaks every hash after it. `verify` walks the chain and reports the first break.

A chain only proves integrity relative to a trusted head hash. The deploy workflow prints the
head hash to the job summary on every append; in production, also write it to WORM storage
(e.g. S3 Object Lock) so an attacker cannot rewrite the whole chain consistently.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

GENESIS = "0" * 64


def digest(body: dict) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append(path: Path, event: str, data: dict, *, ts: int | None = None) -> dict:
    entries = read_entries(path)
    body = {
        "seq": len(entries),
        "ts": int(time.time()) if ts is None else ts,
        "event": event,
        "data": data,
        "prev_hash": entries[-1]["hash"] if entries else GENESIS,
    }
    entry = body | {"hash": digest(body)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
    return entry


def verify(path: Path) -> list[str]:
    errors: list[str] = []
    prev_hash = GENESIS
    for index, entry in enumerate(read_entries(path)):
        body = {k: v for k, v in entry.items() if k != "hash"}
        if entry.get("seq") != index:
            errors.append(f"entry {index}: seq is {entry.get('seq')}, expected {index}")
        if entry.get("prev_hash") != prev_hash:
            errors.append(f"entry {index}: prev_hash does not match entry {index - 1}")
        if digest(body) != entry.get("hash"):
            errors.append(f"entry {index}: content does not match its hash (edited)")
        prev_hash = entry.get("hash", "")
    return errors


def head_hash(path: Path) -> str:
    entries = read_entries(path)
    return entries[-1]["hash"] if entries else GENESIS


def main() -> int:
    parser = argparse.ArgumentParser(description="Hash-chained change ledger")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("append")
    add.add_argument("--ledger", type=Path, required=True)
    add.add_argument("--event", required=True)
    add.add_argument("--data-file", type=Path, required=True)

    check = sub.add_parser("verify")
    check.add_argument("--ledger", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "append":
        with args.data_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        entry = append(args.ledger, args.event, data)
        print(json.dumps({"seq": entry["seq"], "hash": entry["hash"]}))
        return 0

    errors = verify(args.ledger)
    for error in errors:
        print(f"::error::{error}")
    print(f"head={head_hash(args.ledger)} status={'BROKEN' if errors else 'OK'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
