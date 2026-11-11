from __future__ import annotations

import secrets
import re
import uuid
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import quote, urlencode

from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import SECURE_COOKIES, SESSION_COOKIE
from app.database import get_db
from app.models import Account, AuditEvent, LedgerEntry, User, WebSession
from app.money import DUMMY_PASSWORD_HASH, MAX_TRANSACTION_PAISE, create_web_session, current_session, move_money, verify_password
from app.login_throttle import clear_login_failures, login_is_blocked, lock_login_bucket, record_login_failure, throttle_key

app = FastAPI(title="LedgerLine", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'; img-src 'self' data:; style-src 'self';"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if SECURE_COOKIES:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def money(paise: int) -> str:
    sign = "-" if paise < 0 else ""
    absolute = abs(paise)
    return f"{sign}₹{absolute // 100:,.0f}.{absolute % 100:02d}"


templates.env.filters["money"] = money


def get_identity(request: Request, db: Session):
    return current_session(db, request)


def csrf_ok(token: str, session: WebSession) -> bool:
    return bool(token) and secrets.compare_digest(token, session.csrf_token)


def scoped_accounts(db: Session, user: User) -> list[Account]:
    query = select(Account).where(Account.active.is_(True))
    if user.role == "holder":
        query = query.where(Account.owner_id == user.id)
    elif user.role not in {"admin", "auditor"}:
        return []
    return list(db.scalars(query.order_by(Account.name)).all())


def _record_account_creation_refusal(db: Session, actor: User, reason: str, *, owner_id: int | None = None) -> None:
    details = {"reason": reason}
    if owner_id is not None:
        details["requested_owner_id"] = owner_id
    db.add(AuditEvent(actor_id=actor.id, account_id=None, action="account_create", outcome="refused", details=details))
    db.commit()


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    identity = get_identity(request, db)
    return RedirectResponse("/dashboard" if identity else "/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    identity = get_identity(request, db)
    if identity:
        return RedirectResponse("/dashboard", status_code=303)
    token = secrets.token_urlsafe(32)
    response = templates.TemplateResponse(request=request, name="login.html", context={"csrf": token, "error": None})
    response.set_cookie("ledgerline_login_csrf", token, httponly=True, secure=SECURE_COOKIES, samesite="lax", max_age=600)
    return response


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(..., max_length=80), password: str = Form(..., max_length=1024), csrf: str = Form(...), db: Session = Depends(get_db)):
    cookie_token = request.cookies.get("ledgerline_login_csrf", "")
    if not cookie_token or not secrets.compare_digest(cookie_token, csrf):
        return templates.TemplateResponse(request=request, name="login.html", context={"csrf": "", "error": "Refresh the page and try again."}, status_code=403)
    username = username.strip()
    key_hash = throttle_key(username, request.client.host if request.client else "unknown")
    lock_login_bucket(db, key_hash)
    blocked_until = login_is_blocked(db, key_hash)
    if blocked_until:
        retry_after = max(1, int((blocked_until - datetime.now(timezone.utc)).total_seconds()))
        response = templates.TemplateResponse(request=request, name="login.html", context={"csrf": cookie_token, "error": "Too many attempts. Wait before trying again."}, status_code=429)
        response.headers["Retry-After"] = str(retry_after)
        return response
    user = db.scalar(select(User).where(User.username == username))
    valid_password = verify_password(password, user.password_hash if user else DUMMY_PASSWORD_HASH)
    if not user or not user.active or not valid_password:
        record_login_failure(db, key_hash)
        return templates.TemplateResponse(request=request, name="login.html", context={"csrf": cookie_token, "error": "Username or password was not accepted."}, status_code=401)
    clear_login_failures(db, key_hash)
    raw_token, _ = create_web_session(db, user)
    response = RedirectResponse("/dashboard", status_code=303)
    response.delete_cookie("ledgerline_login_csrf")
    response.set_cookie(SESSION_COOKIE, raw_token, httponly=True, secure=SECURE_COOKIES, samesite="lax", path="/", max_age=12 * 60 * 60)
    return response


@app.post("/logout")
def logout(request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    identity = get_identity(request, db)
    if identity:
        user, session = identity
        if csrf_ok(csrf, session):
            db.delete(session)
            db.commit()
        else:
            db.add(AuditEvent(actor_id=user.id, account_id=None, action="logout", outcome="refused", details={"reason": "invalid CSRF token"}))
            db.commit()
            return RedirectResponse("/dashboard?error=Session%20token%20expired", status_code=303)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    identity = get_identity(request, db)
    if not identity:
        return RedirectResponse("/login", status_code=303)
    user, session = identity
    accounts = scoped_accounts(db, user)
    account_ids = [account.id for account in accounts]
    entries = list(db.scalars(select(LedgerEntry).where(LedgerEntry.account_id.in_(account_ids)).order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc()).limit(12)).all()) if account_ids else []
    relevant_ids = {e.actor_id for e in entries} | {a.owner_id for a in accounts if a.owner_id}
    if user.role == "admin":
        relevant_ids.add(user.id)
    people = list(db.scalars(select(User).where(User.id.in_(relevant_ids))).all()) if relevant_ids else []
    actors = {person.id: person.username for person in people}
    holders = list(db.scalars(select(User).where(User.role == "holder", User.active.is_(True)).order_by(User.username)).all()) if user.role == "admin" else []
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"user": user, "session": session, "accounts": accounts, "entries": entries, "actors": actors, "holders": holders, "total": sum(a.balance_paise for a in accounts), "notice": request.query_params.get("notice"), "error": request.query_params.get("error"), "idempotency_key": str(uuid.uuid4())})


@app.get("/accounts/{account_id}", response_class=HTMLResponse)
def statement(account_id: str, request: Request, db: Session = Depends(get_db)):
    identity = get_identity(request, db)
    if not identity:
        return RedirectResponse("/login", status_code=303)
    user, session = identity
    if user.role not in {"admin", "auditor", "holder"}:
        db.add(AuditEvent(actor_id=user.id, account_id=None, action="statement_view", outcome="refused", details={"reason": "unsupported user role"}))
        db.commit()
        return RedirectResponse("/dashboard?error=Account%20not%20available", status_code=303)
    try:
        account_id = str(uuid.UUID(account_id))
    except (ValueError, AttributeError):
        db.add(AuditEvent(actor_id=user.id, account_id=None, action="statement_view", outcome="refused", details={"reason": "invalid account identifier", "requested_account": account_id[:80]}))
        db.commit()
        return RedirectResponse("/dashboard?error=Account%20not%20available", status_code=303)
    query = select(Account).where(Account.id == account_id, Account.active.is_(True))
    if user.role == "holder":
        query = query.where(Account.owner_id == user.id)
    account = db.scalar(query)
    if not account:
        db.add(AuditEvent(actor_id=user.id, account_id=account_id, action="statement_view", outcome="refused", details={"reason": "account not available"}))
        db.commit()
        return RedirectResponse("/dashboard?error=Account%20not%20available", status_code=303)
    entries = list(db.scalars(select(LedgerEntry).where(LedgerEntry.account_id == account.id).order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc()).limit(100)).all())
    refusals = list(db.scalars(select(AuditEvent).where(AuditEvent.account_id == account.id, AuditEvent.outcome == "refused").order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(100)).all())
    replays = list(db.scalars(select(AuditEvent).where(AuditEvent.account_id == account.id, AuditEvent.outcome == "replayed").order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(100)).all())
    actor_ids = {e.actor_id for e in entries} | {e.actor_id for e in refusals} | {e.actor_id for e in replays}
    actors = {u.id: u.username for u in db.scalars(select(User).where(User.id.in_(actor_ids))).all()} if actor_ids else {}
    return templates.TemplateResponse(request=request, name="statement.html", context={"user": user, "session": session, "account": account, "entries": entries, "refusals": refusals, "replays": replays, "actors": actors})


@app.get("/audit", response_class=HTMLResponse)
def audit_log(
    request: Request,
    action: Annotated[str | None, Query(max_length=40)] = None,
    outcome: Annotated[str | None, Query(pattern="^(succeeded|refused|replayed)$")] = None,
    before_id: Annotated[int | None, Query(ge=1, le=9_223_372_036_854_775_807)] = None,
    db: Session = Depends(get_db),
):
    identity = get_identity(request, db)
    if not identity:
        return RedirectResponse("/login", status_code=303)
    user, session = identity
    if user.role not in {"admin", "auditor"}:
        db.add(AuditEvent(actor_id=user.id, account_id=None, action="audit_view", outcome="refused", details={"reason": "administrator or auditor role required"}))
        db.commit()
        return RedirectResponse("/dashboard?error=Not%20authorized", status_code=303)
    query = select(AuditEvent)
    if action:
        query = query.where(AuditEvent.action == action)
    if outcome in {"succeeded", "refused", "replayed"}:
        query = query.where(AuditEvent.outcome == outcome)
    if before_id:
        query = query.where(AuditEvent.id < before_id)
    rows = list(db.scalars(query.order_by(AuditEvent.id.desc()).limit(101)).all())
    has_older = len(rows) > 100
    events = rows[:100]
    actor_ids = {event.actor_id for event in events}
    account_ids = {event.account_id for event in events if event.account_id}
    actors = {person.id: person.username for person in db.scalars(select(User).where(User.id.in_(actor_ids))).all()} if actor_ids else {}
    accounts = {account.id: account.name for account in db.scalars(select(Account).where(Account.id.in_(account_ids))).all()} if account_ids else {}
    actions = list(db.scalars(select(AuditEvent.action).distinct().order_by(AuditEvent.action)).all())
    filters = {key: value for key, value in (("action", action), ("outcome", outcome)) if value}
    older_url = None
    if has_older and events:
        older_url = "/audit?" + urlencode({**filters, "before_id": events[-1].id})
    latest_url = "/audit" + ("?" + urlencode(filters) if filters else "")
    return templates.TemplateResponse(request=request, name="audit.html", context={"user": user, "session": session, "events": events, "actors": actors, "accounts": accounts, "actions": actions, "action_filter": action or "", "outcome_filter": outcome or "", "older_url": older_url, "latest_url": latest_url})


@app.post("/accounts")
def create_account(request: Request, name: str = Form(...), owner_id: int | None = Form(None), csrf: str = Form(...), db: Session = Depends(get_db)):
    identity = get_identity(request, db)
    if not identity:
        return RedirectResponse("/login", status_code=303)
    user, session = identity
    valid_csrf = csrf_ok(csrf, session)
    if not valid_csrf or user.role != "admin":
        _record_account_creation_refusal(db, user, "invalid CSRF token" if not valid_csrf else "administrator role required")
        return RedirectResponse("/dashboard?error=Not%20authorized", status_code=303)
    name = name.strip()
    if not name or len(name) > 120:
        _record_account_creation_refusal(db, user, "account name must contain 1–120 characters")
        return RedirectResponse("/dashboard?error=Enter%20an%20account%20name", status_code=303)
    if owner_id is not None and not db.scalar(select(User.id).where(User.id == owner_id, User.role == "holder", User.active.is_(True))):
        _record_account_creation_refusal(db, user, "owner must be an active account holder", owner_id=owner_id)
        return RedirectResponse("/dashboard?error=Account%20owner%20not%20found", status_code=303)
    account = Account(name=name, owner_id=owner_id, currency="INR", balance_paise=0)
    db.add(account)
    db.flush()
    db.add(AuditEvent(actor_id=user.id, account_id=account.id, action="account_create", outcome="succeeded", details={"name": account.name, "owner_id": owner_id}))
    db.commit()
    return RedirectResponse("/dashboard?notice=Account%20created", status_code=303)


@app.post("/transactions")
def transact(request: Request, action: str = Form(...), amount: str = Form(...), source_id: str = Form(""), destination_id: str = Form(""), idempotency_key: str = Form(...), csrf: str = Form(...), db: Session = Depends(get_db)):
    identity = get_identity(request, db)
    if not identity:
        return RedirectResponse("/login", status_code=303)
    user, session = identity
    if not csrf_ok(csrf, session):
        db.add(AuditEvent(actor_id=user.id, account_id=(source_id or destination_id or None)[:36] if (source_id or destination_id) else None, action="transaction_request", outcome="refused", details={"reason": "invalid anti-CSRF token"}))
        db.commit()
        return RedirectResponse("/dashboard?error=Session%20token%20expired", status_code=303)
    try:
        if len(amount) > 13 or not re.fullmatch(r"[0-9]{1,10}(?:\.[0-9]{1,2})?", amount):
            raise InvalidOperation
        value = Decimal(amount)
        if not value.is_finite() or value <= 0 or value > Decimal(MAX_TRANSACTION_PAISE // 100) or value * 100 != (value * 100).to_integral_value():
            raise InvalidOperation
        paise = int(value * 100)
    except (InvalidOperation, ValueError):
        supplied_account = source_id or destination_id or None
        try:
            account_id = str(uuid.UUID(supplied_account)) if supplied_account else None
        except (ValueError, AttributeError):
            account_id = None
        account = db.scalar(select(Account).where(Account.id == account_id).with_for_update()) if account_id else None
        balance = account.balance_paise if account else None
        db.add(AuditEvent(actor_id=user.id, account_id=account_id, action="transaction_request", outcome="refused", details={"reason": "invalid amount", "requested_amount": amount[:60], "resulting_balance_paise": balance}))
        db.commit()
        return RedirectResponse("/dashboard?error=Enter%20a%20valid%20amount%20with%20up%20to%20two%20decimals", status_code=303)
    result = move_money(db, actor=user, action=action, amount_paise=paise, source_id=source_id or None, destination_id=destination_id or None, idempotency_key=idempotency_key)
    if result.replayed:
        result.message = "This request was already processed; the original result was returned without another money movement."
    key = "notice" if result.ok else "error"
    return RedirectResponse(f"/dashboard?{key}={quote(result.message)}", status_code=303)
