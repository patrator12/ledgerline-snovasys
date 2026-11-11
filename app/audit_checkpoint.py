from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import sys
from collections.abc import Iterable

from sqlalchemy import select

from app.database import SessionLocal
from app.models import AuditEvent

CHECKPOINT_VERSION = b"LedgerLine audit checkpoint v1\0"
MAX_EVENT_ID = 9_223_372_036_854_775_807


def checkpoint_data(events: Iterable[AuditEvent], *, through_id: int | None = None) -> dict[str, int | str]:
    digest = hashlib.sha256(CHECKPOINT_VERSION).digest()
    last_event_id = 0
    for event in events:
        last_event_id = event.id
        record = {
            "id": event.id,
            "actor_id": event.actor_id,
            "account_id": event.account_id,
            "action": event.action,
            "outcome": event.outcome,
            "details": event.details,
            "created_at": event.created_at.isoformat(),
        }
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        digest = hashlib.sha256(digest + payload).digest()
    return {"version": 1, "last_event_id": through_id if through_id is not None else last_event_id, "sha256": digest.hex()}


def checkpoint_digest(events: Iterable[AuditEvent]) -> str:
    return str(checkpoint_data(events)["sha256"])


def audit_checkpoint(*, through_id: int | None = None) -> dict[str, int | str]:
    with SessionLocal() as db:
        query = select(AuditEvent).order_by(AuditEvent.id)
        if through_id is not None:
            query = query.where(AuditEvent.id <= through_id)
        events = db.scalars(query).yield_per(1000)
        return checkpoint_data(events, through_id=through_id)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or verify an out-of-database audit checkpoint.")
    parser.add_argument("--verify", metavar="FILE", help="verify the records through the event ID in a separately stored JSON checkpoint")
    args = parser.parse_args()
    if args.verify:
        try:
            if args.verify == "-":
                expected = json.load(sys.stdin)
            else:
                with open(args.verify, encoding="utf-8") as checkpoint_file:
                    expected = json.load(checkpoint_file)
            if not isinstance(expected, dict) or type(expected.get("version")) is not int or expected["version"] != 1 or type(expected.get("last_event_id")) is not int or not 0 <= expected["last_event_id"] <= MAX_EVENT_ID or not re.fullmatch(r"[0-9a-fA-F]{64}", expected.get("sha256", "")):
                raise ValueError
        except (OSError, ValueError, TypeError, AttributeError):
            parser.error("checkpoint file must contain version 1, a non-negative last_event_id, and a 64-character sha256")
        current = audit_checkpoint(through_id=expected["last_event_id"])
        if not hmac.compare_digest(str(current["sha256"]), expected["sha256"].lower()):
            print("Audit checkpoint mismatch", file=sys.stderr)
            return 1
        print("Audit checkpoint verified")
    else:
        print(json.dumps(audit_checkpoint(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
