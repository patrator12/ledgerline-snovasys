import os
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import MIGRATION_DATABASE_URL
from app.models import Account, AuditEvent, LedgerEntry, User
from app.ledger_chain import append_ledger_entries
from app.money import hash_password


def main() -> None:
    credentials = {
        "admin": os.environ["SEED_ADMIN_PASSWORD"],
        "holder": os.environ["SEED_HOLDER_PASSWORD"],
        "auditor": os.environ["SEED_AUDITOR_PASSWORD"],
    }
    oversized = [role for role, password in credentials.items() if len(password.encode()) > 72]
    if oversized:
        names = ", ".join(f"SEED_{role.upper()}_PASSWORD" for role in oversized)
        raise ValueError(f"Bcrypt passwords must be at most 72 UTF-8 bytes: {names}")
    engine = create_engine(MIGRATION_DATABASE_URL, pool_pre_ping=True)
    with Session(engine) as db:
        people = {}
        for role, password in credentials.items():
            username = f"demo-{role}"
            person = db.scalar(select(User).where(User.username == username))
            if not person:
                person = User(username=username, password_hash=hash_password(password), role=role, kyc_status="APPROVED")
                db.add(person)
                db.flush()
            else:
                person.password_hash = hash_password(password)
            people[role] = person

        for name, balance, owner in [
            ("Operating", 125000000, people["holder"].id),
            ("Reserve", 40000000, people["holder"].id),
            ("Settlement", 0, None),
        ]:
            account = db.scalar(select(Account).where(Account.name == name))
            if account:
                continue
            account = Account(name=name, currency="INR", owner_id=owner, balance_paise=balance)
            db.add(account)
            db.flush()
            if balance:
                transfer_id = str(uuid.uuid4())
                append_ledger_entries(db, [LedgerEntry(transfer_id=transfer_id, account_id=account.id, actor_id=people["admin"].id, amount_paise=balance, side="DEBIT", resulting_balance_paise=balance, kind="opening_balance"), LedgerEntry(transfer_id=transfer_id, account_id=None, actor_id=people["admin"].id, amount_paise=balance, side="CREDIT", contra_account="EXTERNAL_CLEARING", resulting_balance_paise=0, kind="opening_balance")])
            db.add(AuditEvent(actor_id=people["admin"].id, account_id=account.id, action="account_seed", outcome="succeeded", details={"opening_balance_paise": balance}))
        db.commit()
    print("Demo users are ready: demo-admin, demo-holder, demo-auditor. Passwords are the values supplied in SEED_*_PASSWORD.")


if __name__ == "__main__":
    main()
