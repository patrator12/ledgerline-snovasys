from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import LoginThrottle

FAILURE_LIMIT = 5
WINDOW = timedelta(minutes=15)
BLOCK_DURATION = timedelta(minutes=15)
RETENTION = timedelta(days=7)


def throttle_key(username: str, client_ip: str) -> str:
    value = f"{username.strip().casefold()}\0{client_ip}"
    return hashlib.sha256(value.encode()).hexdigest()


def lock_login_bucket(db: Session, key_hash: str) -> None:
    lock_id = int.from_bytes(bytes.fromhex(key_hash[:16]), "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})


def login_is_blocked(db: Session, key_hash: str, *, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(timezone.utc)
    row = db.get(LoginThrottle, key_hash)
    return row.blocked_until if row and row.blocked_until and row.blocked_until > now else None


def record_login_failure(db: Session, key_hash: str, *, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(timezone.utc)
    cutoff = now - WINDOW
    statement = insert(LoginThrottle).values(
        key_hash=key_hash,
        failures=1,
        window_started=now,
        blocked_until=None,
        updated_at=now,
    )
    reset_window = LoginThrottle.window_started <= cutoff
    statement = statement.on_conflict_do_update(
        index_elements=[LoginThrottle.key_hash],
        set_={
            "failures": case((reset_window, 1), else_=LoginThrottle.failures + 1),
            "window_started": case((reset_window, now), else_=LoginThrottle.window_started),
            "blocked_until": case(
                (reset_window, None),
                (LoginThrottle.failures + 1 >= FAILURE_LIMIT, now + BLOCK_DURATION),
                else_=LoginThrottle.blocked_until,
            ),
            "updated_at": now,
        },
    ).returning(LoginThrottle.blocked_until)
    blocked_until = db.scalar(statement)
    prune_old_buckets(db, now=now)
    db.commit()
    return blocked_until


def clear_login_failures(db: Session, key_hash: str, *, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    db.execute(delete(LoginThrottle).where(LoginThrottle.key_hash == key_hash))
    prune_old_buckets(db, now=now)
    db.commit()


def prune_old_buckets(db: Session, *, now: datetime | None = None) -> None:
    cutoff = (now or datetime.now(timezone.utc)) - RETENTION
    stale = (
        select(LoginThrottle.key_hash)
        .where(LoginThrottle.updated_at < cutoff)
        .order_by(LoginThrottle.updated_at)
        .limit(100)
    )
    db.execute(delete(LoginThrottle).where(LoginThrottle.key_hash.in_(stale)))
