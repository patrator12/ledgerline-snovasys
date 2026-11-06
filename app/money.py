from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Request
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import SESSION_COOKIE, SESSION_TTL_HOURS
from app.models import Account, AuditEvent, IdempotencyRecord, LedgerEntry, User, WebSession

password_hasher = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = password_hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return password_hasher.verify(password, encoded)
    except Exception:
        return False


def create_web_session(db: Session, user: User) -> tuple[str, WebSession]:
    raw = secrets.token_urlsafe(32)
    row = WebSession(
        id=secrets.token_hex(16),
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return raw, row


def current_session(db: Session, request: Request) -> tuple[User, WebSession] | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    hashed = hashlib.sha256(token.encode()).hexdigest()
    row = db.scalar(select(WebSession).where(WebSession.token_hash == hashed))
    if row is None or row.expires_at <= datetime.now(timezone.utc):
        if row:
            db.delete(row)
            db.commit()
        return None
    user = db.get(User, row.user_id)
    return (user, row) if user and user.active else None


@dataclass
class MoneyResult:
    ok: bool
    status: str
    message: str
    transfer_id: str | None = None
    replayed: bool = False


def _payload_hash(payload: dict) -> str:
    packed = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(packed.encode()).hexdigest()


def _record_refusal(db: Session, actor: User, account_id: str | None, action: str, amount: int, reason: str, balance: int | None = None) -> None:
    details = {"amount_paise": amount, "reason": reason}
    if balance is not None:
        details["resulting_balance_paise"] = balance
    db.add(AuditEvent(actor_id=actor.id, account_id=account_id, action=action, outcome="refused", details=details))


def _record_replay(db: Session, actor: User, account_id: str | None, amount: int, key: str, result: dict) -> None:
    db.add(AuditEvent(
        actor_id=actor.id,
        account_id=account_id,
        action="idempotency_replay",
        outcome="replayed",
        details={
            "amount_paise": amount,
            "original_transfer_id": result.get("transfer_id"),
            "key_fingerprint": hashlib.sha256(key.encode()).hexdigest()[:16],
        },
    ))
    db.commit()


def _refuse_before_key(db: Session, actor: User, action: str, amount: int, account_id: str | None, reason: str) -> MoneyResult:
    safe_action = action if action in {"deposit", "withdrawal", "transfer"} else "invalid_request"
    try:
        account_id = str(uuid.UUID(account_id)) if account_id else None
    except (ValueError, AttributeError):
        account_id = None
    account = db.scalar(select(Account).where(Account.id == account_id).with_for_update()) if account_id else None
    _record_refusal(db, actor, account_id, safe_action, amount, reason, account.balance_paise if account else None)
    db.commit()
    return MoneyResult(False, "refused", reason)


def move_money(
    db: Session,
    *,
    actor: User,
    action: str,
    amount_paise: int,
    source_id: str | None,
    destination_id: str | None,
    idempotency_key: str,
) -> MoneyResult:
    """Apply one money movement atomically; accounts are locked in sorted order."""
    if action == "deposit":
        source_id = None
    elif action == "withdrawal":
        destination_id = None
    account_ref = source_id or destination_id
    if action not in {"deposit", "withdrawal", "transfer"}:
        return _refuse_before_key(db, actor, action, amount_paise, account_ref, "Unsupported operation")
    for supplied_id in (source_id, destination_id):
        if supplied_id:
            try:
                normalized_id = str(uuid.UUID(supplied_id))
            except (ValueError, AttributeError):
                db.add(AuditEvent(actor_id=actor.id, account_id=None, action="transaction_request", outcome="refused", details={"reason": "invalid account identifier", "requested_account": supplied_id[:80], "amount_paise": amount_paise}))
                db.commit()
                return MoneyResult(False, "refused", "Account identifier is invalid")
            if supplied_id == source_id:
                source_id = normalized_id
            if supplied_id == destination_id:
                destination_id = normalized_id
    account_ref = source_id or destination_id
    if amount_paise <= 0 or amount_paise > 100_000_000_000:
        return _refuse_before_key(db, actor, action, amount_paise, account_ref, "Amount must be positive and within the demo limit")
    if len(idempotency_key) < 8 or len(idempotency_key) > 100:
        return _refuse_before_key(db, actor, action, amount_paise, account_ref, "Idempotency key must be 8–100 characters")

    payload = {"action": action, "amount_paise": amount_paise, "source_id": source_id, "destination_id": destination_id}
    digest = _payload_hash(payload)
    existing = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.actor_id == actor.id, IdempotencyRecord.key == idempotency_key))
    if existing:
        if existing.request_hash != digest:
            account = db.get(Account, source_id or destination_id) if (source_id or destination_id) else None
            _record_refusal(db, actor, source_id or destination_id, action, amount_paise, "idempotency key reused with different request", account.balance_paise if account else None)
            db.commit()
            return MoneyResult(False, "refused", "This idempotency key belongs to a different request")
        previous = existing.result or {}
        _record_replay(db, actor, source_id or destination_id, amount_paise, idempotency_key, previous)
        return MoneyResult(previous.get("ok", False), previous.get("status", "refused"), previous.get("message", "Request in progress"), previous.get("transfer_id"), True)

    record = IdempotencyRecord(actor_id=actor.id, key=idempotency_key, request_hash=digest, result=None)
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        prior = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.actor_id == actor.id, IdempotencyRecord.key == idempotency_key))
        if prior and prior.request_hash == digest and prior.result:
            res = prior.result
            _record_replay(db, actor, source_id or destination_id, amount_paise, idempotency_key, res)
            return MoneyResult(res["ok"], res["status"], res["message"], res.get("transfer_id"), True)
        return MoneyResult(False, "refused", "A request with this key is already being processed")

    involved_ids = sorted({i for i in (source_id, destination_id) if i})
    accounts = db.scalars(select(Account).where(Account.id.in_(involved_ids)).order_by(Account.id).with_for_update()).all() if involved_ids else []
    by_id = {account.id: account for account in accounts}
    source = by_id.get(source_id)
    destination = by_id.get(destination_id)

    reason = None
    if action == "deposit" and actor.role != "admin":
        reason = "Only administrators can deposit funds"
    elif action in {"withdrawal", "transfer"} and actor.role not in {"admin", "holder"}:
        reason = "This role cannot move funds"
    elif action in {"withdrawal", "transfer"} and (source is None or not source.active):
        reason = "source account not found or inactive"
    elif action == "deposit" and (destination is None or not destination.active):
        reason = "destination account not found or inactive"
    elif action == "transfer" and (destination is None or not destination.active or destination.id == source_id):
        reason = "destination account not found, inactive, or same as source"
    elif actor.role == "holder" and any(a.owner_id != actor.id for a in accounts):
        reason = "account is not owned by this user"
    elif action in {"withdrawal", "transfer"} and source.balance_paise < amount_paise:
        reason = "insufficient funds"

    transfer_id = str(uuid.uuid4())
    if reason:
        affected = source_id or destination_id
        balance = (source.balance_paise if source else destination.balance_paise if destination else None)
        _record_refusal(db, actor, affected, action, amount_paise, reason, balance)
        result = MoneyResult(False, "refused", reason)
    else:
        if action == "deposit":
            destination.balance_paise += amount_paise
            postings = [(destination, amount_paise, "deposit")]
        elif action == "withdrawal":
            source.balance_paise -= amount_paise
            postings = [(source, -amount_paise, "withdrawal")]
        else:
            source.balance_paise -= amount_paise
            destination.balance_paise += amount_paise
            postings = [(source, -amount_paise, "transfer_out"), (destination, amount_paise, "transfer_in")]
        for account, delta, kind in postings:
            db.add(LedgerEntry(transfer_id=transfer_id, account_id=account.id, actor_id=actor.id, amount_paise=delta, resulting_balance_paise=account.balance_paise, kind=kind))
        db.add(AuditEvent(actor_id=actor.id, account_id=source_id or destination_id, action=action, outcome="succeeded", details={"transfer_id": transfer_id, "amount_paise": amount_paise}))
        result = MoneyResult(True, "succeeded", "Money movement recorded", transfer_id)

    record.result = {"ok": result.ok, "status": result.status, "message": result.message, "transfer_id": result.transfer_id}
    db.commit()
    return result
