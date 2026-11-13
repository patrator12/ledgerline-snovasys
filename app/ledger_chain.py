from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import LedgerEntry

GENESIS_HASH = "0" * 64
CHAIN_LOCK_KEY = 7_681_126_041


def ledger_entry_digest(entry: LedgerEntry, previous_hash: str) -> str:
    created_at = entry.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    material = {
        "version": 1,
        "previous_hash": previous_hash,
        "transfer_id": str(entry.transfer_id),
        "account_id": str(entry.account_id) if entry.account_id else None,
        "actor_id": entry.actor_id,
        "amount_paise": entry.amount_paise,
        "side": entry.side,
        "contra_account": entry.contra_account,
        "resulting_balance_paise": entry.resulting_balance_paise,
        "kind": entry.kind,
        "created_at": created_at.astimezone(timezone.utc).isoformat(timespec="microseconds"),
    }
    payload = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def append_ledger_entries(db: Session, entries: list[LedgerEntry]) -> None:
    if not entries:
        return
    connection = db.connection()
    connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CHAIN_LOCK_KEY})
    previous_hash = connection.execute(text("SELECT entry_hash FROM ledger_entries ORDER BY id DESC LIMIT 1")).scalar_one_or_none() or GENESIS_HASH
    for entry in sorted(entries, key=lambda row: (row.account_id or "", row.kind)):
        if entry.created_at is None:
            entry.created_at = datetime.now(timezone.utc)
        entry.previous_hash = previous_hash
        entry.entry_hash = ledger_entry_digest(entry, previous_hash)
        db.add(entry)
        db.flush()
        previous_hash = entry.entry_hash


def verify_ledger(db: Session) -> dict:
    from app.models import Account

    accounts = {account.id: account for account in db.scalars(select(Account).execution_options(populate_existing=True)).all()}
    entries = list(db.scalars(select(LedgerEntry).order_by(LedgerEntry.id).execution_options(populate_existing=True)).all())
    expected_previous = GENESIS_HASH
    chain_valid = True
    balance_totals: dict[str, int] = {}
    transfers: dict[str, list[LedgerEntry]] = {}
    for entry in entries:
        if entry.previous_hash != expected_previous or entry.entry_hash != ledger_entry_digest(entry, entry.previous_hash):
            chain_valid = False
        expected_previous = entry.entry_hash
        if entry.account_id:
            signed_amount = entry.amount_paise if entry.side == "DEBIT" else -entry.amount_paise
            balance_totals[entry.account_id] = balance_totals.get(entry.account_id, 0) + signed_amount
        transfers.setdefault(str(entry.transfer_id), []).append(entry)

    balance_mismatches = sum(account.balance_paise != balance_totals.get(account_id, 0) for account_id, account in accounts.items())
    transfer_groups = list(transfers.values())
    transfer_mismatches = sum(
        len(rows) != 2
        or sum(row.amount_paise for row in rows if row.side == "DEBIT") != sum(row.amount_paise for row in rows if row.side == "CREDIT")
        for rows in transfer_groups
    )
    balances_valid = balance_mismatches == 0
    transfers_valid = transfer_mismatches == 0
    return {
        "valid": chain_valid and balances_valid and transfers_valid,
        "entries_checked": len(entries),
        "last_entry_id": entries[-1].id if entries else None,
        "head_hash": expected_previous,
        "hash_chain": {"valid": chain_valid},
        "account_balance_parity": {"valid": balances_valid, "accounts_checked": len(accounts), "mismatches": balance_mismatches},
        "transfer_posting_parity": {"valid": transfers_valid, "transfers_checked": len(transfer_groups), "mismatches": transfer_mismatches},
    }
