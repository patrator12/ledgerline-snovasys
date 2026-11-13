"""Exercise the one-time upgrade against the pre-double-entry PostgreSQL schema."""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from app.init_db import upgrade_double_entry, upgrade_ledger_hash_chain


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def test_legacy_signed_rows_migrate_to_balanced_postings_and_valid_chain():
    if not TEST_DATABASE_URL:
        pytest.skip("Set TEST_DATABASE_URL to an isolated PostgreSQL database")

    admin_engine = create_engine(TEST_DATABASE_URL)
    schema = f"ledger_migration_{uuid.uuid4().hex}"
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    migration_engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"options": f"-c search_path={schema}"},
    )
    try:
        with migration_engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE ledger_entries (
                    id BIGSERIAL PRIMARY KEY,
                    transfer_id UUID NOT NULL,
                    account_id UUID NOT NULL,
                    actor_id INTEGER NOT NULL,
                    amount_paise BIGINT NOT NULL,
                    resulting_balance_paise BIGINT NOT NULL CHECK (resulting_balance_paise >= 0),
                    kind VARCHAR(24) NOT NULL,
                    previous_hash VARCHAR(64) NOT NULL,
                    entry_hash VARCHAR(64) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    CONSTRAINT ck_ledger_nonzero_posting CHECK (amount_paise <> 0)
                )
            """))
            connection.execute(text("CREATE UNIQUE INDEX uq_ledger_entries_entry_hash ON ledger_entries(entry_hash)"))

            account_a, account_b = str(uuid.uuid4()), str(uuid.uuid4())
            entries = [
                (uuid.uuid4(), account_a, 10_000, 10_000, "opening_balance"),
                (uuid.uuid4(), account_a, 5_000, 15_000, "deposit"),
                (uuid.uuid4(), account_a, -2_000, 13_000, "withdrawal"),
            ]
            transfer_id = uuid.uuid4()
            entries.extend([
                (transfer_id, account_a, -3_000, 10_000, "transfer_out"),
                (transfer_id, account_b, 3_000, 3_000, "transfer_in"),
            ])
            connection.execute(text("""
                INSERT INTO ledger_entries
                    (transfer_id, account_id, actor_id, amount_paise, resulting_balance_paise,
                     kind, previous_hash, entry_hash, created_at)
                VALUES (:transfer_id, :account_id, 1, :amount, :balance, :kind, :previous, :digest, now())
            """), [
                {
                    "transfer_id": str(transfer_id),
                    "account_id": account_id,
                    "amount": amount,
                    "balance": balance,
                    "kind": kind,
                    "previous": f"{index:064x}",
                    "digest": f"{index + 1:064x}",
                }
                for index, (transfer_id, account_id, amount, balance, kind) in enumerate(entries)
            ])

        upgrade_double_entry(migration_engine)
        upgrade_double_entry(migration_engine)
        upgrade_ledger_hash_chain(migration_engine)

        with migration_engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT transfer_id::text, account_id::text, amount_paise, side, contra_account,
                       kind, resulting_balance_paise, previous_hash, entry_hash
                FROM ledger_entries ORDER BY id
            """)).mappings().all()

    finally:
        migration_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()

    assert len(rows) == 8
    assert all(row["amount_paise"] > 0 for row in rows)
    clearing_rows = [row for row in rows if row["account_id"] is None]
    assert len(clearing_rows) == 3
    assert all(row["contra_account"] == "EXTERNAL_CLEARING" for row in clearing_rows)
    assert {
        (row["kind"], row["side"])
        for row in rows
        if row["account_id"] is not None
    } == {
        ("opening_balance", "DEBIT"),
        ("deposit", "DEBIT"),
        ("withdrawal", "CREDIT"),
        ("transfer_out", "CREDIT"),
        ("transfer_in", "DEBIT"),
    }

    groups = {}
    balances = {}
    for row in rows:
        groups.setdefault(row["transfer_id"], []).append(row)
        if row["account_id"]:
            side_sign = 1 if row["side"] == "DEBIT" else -1
            balances[row["account_id"]] = balances.get(row["account_id"], 0) + side_sign * row["amount_paise"]

    assert len(groups) == 4
    for postings in groups.values():
        assert len(postings) == 2
        assert sum(row["amount_paise"] for row in postings if row["side"] == "DEBIT") == sum(
            row["amount_paise"] for row in postings if row["side"] == "CREDIT"
        )
    assert sorted(balances.values()) == [3_000, 10_000]
    assert all(row["previous_hash"] and row["entry_hash"] for row in rows)
