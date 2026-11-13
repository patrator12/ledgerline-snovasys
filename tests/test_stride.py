"""Dedicated STRIDE regression tests over a disposable PostgreSQL database."""

import os
import uuid

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.config import SESSION_COOKIE
from app.database import Base
from app.init_db import install_append_only_guard, upgrade_audit_outcomes, upgrade_governance_fields, upgrade_ledger_hash_chain
from app.ledger_chain import append_ledger_entries
from app.main import app as fastapi_app, login, set_account_frozen, statement, update_kyc
from app.models import Account, AuditEvent, LedgerEntry, User
from app.money import create_web_session, current_session, move_money

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database", allow_module_level=True)

engine = create_engine(TEST_DATABASE_URL, pool_size=10, max_overflow=10)
TestingSession = sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def clean_stride_database():
    Base.metadata.create_all(bind=engine)
    upgrade_audit_outcomes(engine)
    upgrade_governance_fields(engine)
    upgrade_ledger_hash_chain(engine)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE audit_events, ledger_entries, idempotency_records, web_sessions, login_throttles, accounts, users RESTART IDENTITY CASCADE"))
    install_append_only_guard(engine, "ledger_entries")
    install_append_only_guard(engine, "audit_events")


@pytest.fixture
def actors_and_accounts():
    with TestingSession() as db:
        admin = User(username="stride-admin", password_hash="unused", role="admin", kyc_status="APPROVED")
        holder = User(username="stride-holder", password_hash="unused", role="holder", kyc_status="APPROVED")
        stranger = User(username="stride-stranger", password_hash="unused", role="holder", kyc_status="APPROVED")
        auditor = User(username="stride-auditor", password_hash="unused", role="auditor", kyc_status="APPROVED")
        db.add_all([admin, holder, stranger, auditor])
        db.flush()
        source = Account(name="Stride source", owner_id=holder.id, balance_paise=10_000)
        destination = Account(name="Stride destination", owner_id=holder.id, balance_paise=0)
        private = Account(name="Stride private", owner_id=stranger.id, balance_paise=5_000)
        db.add_all([source, destination, private])
        db.flush()
        entries = []
        for account, amount in ((source, 10_000), (private, 5_000)):
            transfer_id = str(uuid.uuid4())
            entries.extend([LedgerEntry(transfer_id=transfer_id, account_id=account.id, actor_id=admin.id, amount_paise=amount, side="DEBIT", resulting_balance_paise=amount, kind="opening_balance"), LedgerEntry(transfer_id=transfer_id, account_id=None, actor_id=admin.id, amount_paise=amount, side="CREDIT", contra_account="EXTERNAL_CLEARING", resulting_balance_paise=0, kind="opening_balance")])
        append_ledger_entries(db, entries)
        db.commit()
        return {"admin": admin.id, "holder": holder.id, "stranger": stranger.id, "auditor": auditor.id,
                "source": source.id, "destination": destination.id, "private": private.id}


def authenticated_request(token, path="/accounts", method="POST"):
    return Request({
        "type": "http", "http_version": "1.1", "method": method, "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"",
        "headers": [(b"cookie", f"{SESSION_COOKIE}={token}".encode())],
        "client": ("testclient", 50000), "server": ("testserver", 80), "app": fastapi_app,
    })


def login_request(csrf):
    return Request({
        "type": "http", "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/login", "raw_path": b"/login", "query_string": b"",
        "headers": [(b"cookie", f"ledgerline_login_csrf={csrf}".encode())],
        "client": ("testclient", 50000), "server": ("testserver", 80), "app": fastapi_app,
    })


def move(actor_id, *, action, amount, source=None, key=None):
    with TestingSession() as db:
        actor = db.get(User, actor_id)
        return move_money(db, actor=actor, action=action, amount_paise=amount, source_id=source,
                          destination_id=None, idempotency_key=key or str(uuid.uuid4()))


def test_spoofing_forged_session_cookie_is_rejected(actors_and_accounts):
    ids = actors_and_accounts
    with TestingSession() as db:
        holder = db.get(User, ids["holder"])
        token, _ = create_web_session(db, holder)
        forged = token[:-1] + ("A" if token[-1] != "A" else "B")
        assert current_session(db, authenticated_request(token)) is not None
        assert current_session(db, authenticated_request(forged)) is None


def test_tampering_update_to_ledger_entry_is_rejected(actors_and_accounts):
    ids = actors_and_accounts
    result = move(ids["holder"], action="withdrawal", amount=100, source=ids["source"], key="stride-tamper-01")
    assert result.ok
    with TestingSession() as db, pytest.raises(Exception, match="append-only"):
        db.execute(text("UPDATE ledger_entries SET amount_paise = 0 WHERE transfer_id = :id"), {"id": uuid.UUID(result.transfer_id)})
        db.commit()


def test_repudiation_refused_cross_account_attempt_is_audited(actors_and_accounts):
    ids = actors_and_accounts
    result = move(ids["holder"], action="withdrawal", amount=100, source=ids["private"], key="stride-repudiate-01")
    assert not result.ok
    with TestingSession() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.actor_id == ids["holder"], AuditEvent.outcome == "refused"))
        assert event is not None
        assert event.details["reason"] == "account is not owned by this user"


def test_information_disclosure_holder_cannot_open_another_statement(actors_and_accounts):
    ids = actors_and_accounts
    with TestingSession() as db:
        holder = db.get(User, ids["holder"])
        token, _ = create_web_session(db, holder)
        response = statement(ids["private"], authenticated_request(token, f"/accounts/{ids['private']}", "GET"), db)
        assert response.status_code == 303
        assert response.headers["location"].startswith("/dashboard?error=")
        assert db.scalar(select(AuditEvent.id).where(AuditEvent.action == "statement_view", AuditEvent.outcome == "refused")) is not None


def test_denial_of_service_login_throttle_blocks_repeated_failures(actors_and_accounts):
    with TestingSession() as db:
        csrf = "stride-login-csrf"
        for _ in range(5):
            assert login(login_request(csrf), "unknown-user", "wrong-password", csrf, db).status_code == 401
        assert login(login_request(csrf), "unknown-user", "wrong-password", csrf, db).status_code == 429


def test_elevation_of_privilege_auditor_cannot_change_governance(actors_and_accounts):
    ids = actors_and_accounts
    with TestingSession() as db:
        auditor = db.get(User, ids["auditor"])
        token, session = create_web_session(db, auditor)
        frozen = set_account_frozen(ids["source"], authenticated_request(token, f"/accounts/{ids['source']}/freeze"), "true", session.csrf_token, db)
        kyc = update_kyc(ids["holder"], authenticated_request(token, f"/users/{ids['holder']}/kyc"), "REJECTED", session.csrf_token, db)
        assert frozen.status_code == kyc.status_code == 303
        assert not db.get(Account, ids["source"]).frozen
        assert db.get(User, ids["holder"]).kyc_status == "APPROVED"
        assert db.scalar(select(AuditEvent.id).where(AuditEvent.action == "account_freeze", AuditEvent.outcome == "refused")) is not None
        assert db.scalar(select(AuditEvent.id).where(AuditEvent.action == "kyc_review", AuditEvent.outcome == "refused")) is not None
