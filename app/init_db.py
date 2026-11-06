from sqlalchemy import create_engine, text

from app.config import MIGRATION_DATABASE_URL
from app.database import Base
from app import models  # noqa: F401


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
    install_append_only_guard(engine, "ledger_entries")
    install_append_only_guard(engine, "audit_events")
    app_user = "ledgerline_app"
    with engine.begin() as connection:
        connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {app_user}"))
        connection.execute(text(f"GRANT SELECT ON users TO {app_user}"))
        connection.execute(text(f"GRANT SELECT, INSERT, DELETE ON web_sessions TO {app_user}"))
        connection.execute(text(f"GRANT SELECT, INSERT ON accounts, idempotency_records TO {app_user}"))
        connection.execute(text(f"GRANT UPDATE (balance_paise) ON accounts TO {app_user}"))
        connection.execute(text(f"GRANT UPDATE (result) ON idempotency_records TO {app_user}"))
        connection.execute(text(f"GRANT SELECT, INSERT ON ledger_entries, audit_events TO {app_user}"))
        connection.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {app_user}"))
    print("LedgerLine schema and append-only guards are ready.")
