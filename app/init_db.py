from types import SimpleNamespace

from sqlalchemy import create_engine, inspect, text

from app.config import MIGRATION_DATABASE_URL
from app.database import Base
from app import models  # noqa: F401
from app.ledger_chain import CHAIN_LOCK_KEY, GENESIS_HASH, ledger_entry_digest


def upgrade_audit_outcomes(engine) -> None:
    """Allow the explicit replay outcome on both fresh and existing databases."""
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE audit_events DROP CONSTRAINT IF EXISTS ck_audit_valid_outcome"))
        connection.execute(text("ALTER TABLE audit_events ADD CONSTRAINT ck_audit_valid_outcome CHECK (outcome IN ('succeeded', 'refused', 'replayed'))"))


def upgrade_governance_fields(engine) -> None:
    """Add KYC and account-freeze state while preserving existing access."""
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS kyc_status VARCHAR(16) NOT NULL DEFAULT 'APPROVED'"))
        connection.execute(text("ALTER TABLE users ALTER COLUMN kyc_status DROP DEFAULT"))
        connection.execute(text("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS frozen BOOLEAN NOT NULL DEFAULT FALSE"))
        connection.execute(text("ALTER TABLE accounts ALTER COLUMN frozen DROP DEFAULT"))
        connection.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_user_valid_kyc_status"))
        connection.execute(text("ALTER TABLE users ADD CONSTRAINT ck_user_valid_kyc_status CHECK (kyc_status IN ('PENDING', 'APPROVED', 'REJECTED'))"))


def upgrade_ledger_hash_chain(engine) -> None:
    """Backfill the first chain once; fail closed if an existing chain is invalid."""
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CHAIN_LOCK_KEY})
        existing_columns = {column["name"] for column in inspect(connection).get_columns("ledger_entries")}
        chain_schema_existed = bool({"previous_hash", "entry_hash"} & existing_columns)
        connection.execute(text("DROP TRIGGER IF EXISTS ledger_entries_append_only ON ledger_entries"))
        connection.execute(text("ALTER TABLE ledger_entries ADD COLUMN IF NOT EXISTS previous_hash VARCHAR(64)"))
        connection.execute(text("ALTER TABLE ledger_entries ADD COLUMN IF NOT EXISTS entry_hash VARCHAR(64)"))
        rows = list(connection.execute(text("SELECT id, transfer_id::text AS transfer_id, account_id::text AS account_id, actor_id, amount_paise, resulting_balance_paise, kind, created_at, previous_hash, entry_hash FROM ledger_entries ORDER BY id")).mappings())
        incomplete = [row for row in rows if row["previous_hash"] is None or row["entry_hash"] is None]
        if incomplete and len(incomplete) != len(rows):
            raise RuntimeError("Ledger hash chain is partially populated; refusing to rewrite it")
        if incomplete and chain_schema_existed:
            raise RuntimeError("Ledger hash chain columns already existed but contain empty values; refusing to rebuild it")
        previous_hash = GENESIS_HASH
        for row in rows:
            entry = SimpleNamespace(
                transfer_id=row["transfer_id"], account_id=row["account_id"], actor_id=row["actor_id"],
                amount_paise=row["amount_paise"], resulting_balance_paise=row["resulting_balance_paise"],
                kind=row["kind"], created_at=row["created_at"],
            )
            if incomplete:
                entry_hash = ledger_entry_digest(entry, previous_hash)
                connection.execute(text("UPDATE ledger_entries SET previous_hash = :previous_hash, entry_hash = :entry_hash WHERE id = :id"), {"previous_hash": previous_hash, "entry_hash": entry_hash, "id": row["id"]})
            else:
                entry_hash = row["entry_hash"]
                if row["previous_hash"] != previous_hash or entry_hash != ledger_entry_digest(entry, previous_hash):
                    raise RuntimeError(f"Ledger hash chain verification failed at entry {row['id']}")
            previous_hash = entry_hash
        connection.execute(text("ALTER TABLE ledger_entries ALTER COLUMN previous_hash SET NOT NULL"))
        connection.execute(text("ALTER TABLE ledger_entries ALTER COLUMN entry_hash SET NOT NULL"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_entries_entry_hash ON ledger_entries(entry_hash)"))


def install_append_only_guard(engine, table_name: str) -> None:
    with engine.begin() as connection:
        connection.execute(text(f"""
        CREATE OR REPLACE FUNCTION prevent_{table_name}_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION '{table_name} is append-only';
        END;
        $$ LANGUAGE plpgsql
        """))
        connection.execute(text(f"DROP TRIGGER IF EXISTS {table_name}_append_only ON {table_name}"))
        connection.execute(text(f"""
        CREATE TRIGGER {table_name}_append_only
          BEFORE UPDATE OR DELETE ON {table_name}
          FOR EACH ROW EXECUTE FUNCTION prevent_{table_name}_mutation()
        """))


if __name__ == "__main__":
    engine = create_engine(MIGRATION_DATABASE_URL, pool_pre_ping=True)
    Base.metadata.create_all(bind=engine)
    upgrade_audit_outcomes(engine)
    upgrade_governance_fields(engine)
    upgrade_ledger_hash_chain(engine)
    install_append_only_guard(engine, "ledger_entries")
    install_append_only_guard(engine, "audit_events")
    app_user = "ledgerline_app"
    with engine.begin() as connection:
        connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {app_user}"))
        connection.execute(text(f"GRANT SELECT ON users TO {app_user}"))
        connection.execute(text(f"GRANT UPDATE (kyc_status) ON users TO {app_user}"))
        connection.execute(text(f"GRANT SELECT, INSERT, DELETE ON web_sessions TO {app_user}"))
        connection.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON login_throttles TO {app_user}"))
        connection.execute(text(f"GRANT SELECT, INSERT ON accounts, idempotency_records TO {app_user}"))
        connection.execute(text(f"GRANT UPDATE (balance_paise) ON accounts TO {app_user}"))
        connection.execute(text(f"GRANT UPDATE (frozen) ON accounts TO {app_user}"))
        connection.execute(text(f"GRANT UPDATE (result) ON idempotency_records TO {app_user}"))
        connection.execute(text(f"GRANT SELECT, INSERT ON ledger_entries, audit_events TO {app_user}"))
        connection.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {app_user}"))
    print("LedgerLine schema and append-only guards are ready.")
