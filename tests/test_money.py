"""Integration tests for money invariants. Set TEST_DATABASE_URL to a disposable PostgreSQL database."""

import os
import threading
import uuid

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.init_db import install_append_only_guard, upgrade_audit_outcomes
from app.models import Account, AuditEvent, IdempotencyRecord, LedgerEntry, User
from app.money import move_money


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database", allow_module_level=True)

engine = create_engine(TEST_DATABASE_URL, pool_size=10, max_overflow=10)
TestingSession = sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def clean_database():
    """These tests only run against the explicitly named disposable test database."""
    Base.metadata.create_all(bind=engine)
    upgrade_audit_outcomes(engine)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE audit_events, ledger_entries, idempotency_records, web_sessions, accounts, users RESTART IDENTITY CASCADE"))
    install_append_only_guard(engine, "ledger_entries")
    install_append_only_guard(engine, "audit_events")
    yield


@pytest.fixture
def actors_and_accounts():
    with TestingSession() as db:
        admin = User(username="admin", password_hash="unused", role="admin")
        holder = User(username="holder", password_hash="unused", role="holder")
        stranger = User(username="stranger", password_hash="unused", role="holder")
        auditor = User(username="auditor", password_hash="unused", role="auditor")
        db.add_all([admin, holder, stranger, auditor])
        db.flush()
        source = Account(name="Source", owner_id=holder.id, balance_paise=10_000)
        destination = Account(name="Destination", owner_id=holder.id, balance_paise=0)
        stranger_account = Account(name="Private", owner_id=stranger.id, balance_paise=5_000)
        db.add_all([source, destination, stranger_account])
        db.commit()
        return {"admin": admin.id, "holder": holder.id, "stranger": stranger.id, "auditor": auditor.id,
                "source": source.id, "destination": destination.id, "private": stranger_account.id}


def run_movement(actor_id, *, action, amount, source=None, destination=None, key=None):
    with TestingSession() as db:
        actor = db.get(User, actor_id)
        return move_money(db, actor=actor, action=action, amount_paise=amount, source_id=source,
                          destination_id=destination, idempotency_key=key or str(uuid.uuid4()))


def test_transfer_balances_both_accounts_and_conserves_total(actors_and_accounts):
    ids = actors_and_accounts
    before = 10_000
    result = run_movement(ids["holder"], action="transfer", amount=3_250, source=ids["source"], destination=ids["destination"], key="transfer-key-0001")
    assert result.ok
    with TestingSession() as db:
        source = db.get(Account, ids["source"])
        destination = db.get(Account, ids["destination"])
        postings = list(db.scalars(select(LedgerEntry).where(LedgerEntry.transfer_id == result.transfer_id)).all())
        assert source.balance_paise == 6_750
        assert destination.balance_paise == 3_250
        assert source.balance_paise + destination.balance_paise == before
        assert sum(item.amount_paise for item in postings) == 0


def test_external_deposit_and_withdrawal_change_total_by_their_amount(actors_and_accounts):
    ids = actors_and_accounts
    deposit = run_movement(ids["admin"], action="deposit", amount=500, destination=ids["destination"], key="deposit-key-0001")
    withdrawal = run_movement(ids["holder"], action="withdrawal", amount=200, source=ids["source"], key="withdraw-key-001")
    assert deposit.ok and withdrawal.ok
    with TestingSession() as db:
        total = sum(db.scalars(select(Account.balance_paise)).all())
        assert total == 15_300


def test_replayed_idempotency_key_returns_original_result_without_second_posting(actors_and_accounts):
    ids = actors_and_accounts
    first = run_movement(ids["holder"], action="transfer", amount=2_000, source=ids["source"], destination=ids["destination"], key="retry-key-00001")
    replay = run_movement(ids["holder"], action="transfer", amount=2_000, source=ids["source"], destination=ids["destination"], key="retry-key-00001")
    assert first.ok and replay.ok and replay.replayed
    assert first.transfer_id == replay.transfer_id
    with TestingSession() as db:
        assert db.scalar(select(Account.balance_paise).where(Account.id == ids["source"])) == 8_000
        assert len(db.scalars(select(LedgerEntry).where(LedgerEntry.transfer_id == first.transfer_id)).all()) == 2
        replay_events = list(db.scalars(select(AuditEvent).where(AuditEvent.outcome == "replayed")).all())
        assert len(replay_events) == 1
        assert replay_events[0].details["original_transfer_id"] == first.transfer_id
        assert len(replay_events[0].details["key_fingerprint"]) == 16


def test_reusing_key_for_different_payload_is_refused(actors_and_accounts):
    ids = actors_and_accounts
    first = run_movement(ids["holder"], action="transfer", amount=1_000, source=ids["source"], destination=ids["destination"], key="same-key-00001")
    second = run_movement(ids["holder"], action="transfer", amount=1_500, source=ids["source"], destination=ids["destination"], key="same-key-00001")
    assert first.ok and not second.ok
    with TestingSession() as db:
        assert db.scalar(select(Account.balance_paise).where(Account.id == ids["source"])) == 9_000


def test_account_holder_cannot_move_someone_elses_funds(actors_and_accounts):
    ids = actors_and_accounts
    result = run_movement(ids["holder"], action="withdrawal", amount=1_000, source=ids["private"], key="cross-account-001")
    assert not result.ok
    with TestingSession() as db:
        assert db.scalar(select(Account.balance_paise).where(Account.id == ids["private"])) == 5_000
        assert db.scalar(select(AuditEvent.id).where(AuditEvent.account_id == ids["private"], AuditEvent.outcome == "refused")) is not None


def test_concurrent_withdrawals_cannot_overdraw(actors_and_accounts):
    ids = actors_and_accounts
    barrier = threading.Barrier(2)
    outcomes = []
    outcome_lock = threading.Lock()

    def withdraw(key):
        barrier.wait(timeout=5)
        result = run_movement(ids["holder"], action="withdrawal", amount=8_000, source=ids["source"], key=key)
        with outcome_lock:
            outcomes.append(result)

    workers = [threading.Thread(target=withdraw, args=(f"race-key-{index:05d}",)) for index in (1, 2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)
    assert all(not worker.is_alive() for worker in workers)
    assert sum(result.ok for result in outcomes) == 1
    with TestingSession() as db:
        balance = db.scalar(select(Account.balance_paise).where(Account.id == ids["source"]))
        assert balance == 2_000
        assert balance >= 0


def test_auditor_cannot_move_money(actors_and_accounts):
    ids = actors_and_accounts
    result = run_movement(ids["auditor"], action="withdrawal", amount=100, source=ids["source"], key="audit-role-0001")
    assert not result.ok
    with TestingSession() as db:
        assert db.scalar(select(Account.balance_paise).where(Account.id == ids["source"])) == 10_000


@pytest.mark.parametrize("table", ["ledger_entries", "audit_events"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_financial_and_audit_rows_are_database_append_only(actors_and_accounts, table, operation):
    ids = actors_and_accounts
    result = run_movement(ids["holder"], action="withdrawal", amount=100, source=ids["source"], key="append-only-0001")
    assert result.ok
    with TestingSession() as db, pytest.raises(Exception, match="append-only"):
        if table == "ledger_entries":
            db.execute(text(f"{operation} ledger_entries SET amount_paise = 0 WHERE transfer_id = :id"), {"id": uuid.UUID(result.transfer_id)})
        else:
            db.execute(text(f"{operation} audit_events SET action = 'tampered' WHERE details ->> 'transfer_id' = :id"), {"id": result.transfer_id})
        db.commit()
