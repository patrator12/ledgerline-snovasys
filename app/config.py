import os


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://ledgerline:ledgerline@localhost:5432/ledgerline")
SESSION_COOKIE = "__Host-ledgerline" if os.getenv("APP_ENV") == "production" else "ledgerline_session"
SESSION_TTL_HOURS = 12
SESSION_SIGNING_KEY = os.getenv("SESSION_SIGNING_KEY", "")
if not SESSION_SIGNING_KEY:
    raise RuntimeError("SESSION_SIGNING_KEY must be set")
if len(SESSION_SIGNING_KEY.encode()) < 32:
    raise RuntimeError("SESSION_SIGNING_KEY must contain at least 32 bytes")
IDEMPOTENCY_TTL_HOURS = 24
SECURE_COOKIES = os.getenv("APP_ENV", "development") == "production"
MIGRATION_DATABASE_URL = os.getenv("MIGRATION_DATABASE_URL", DATABASE_URL)
