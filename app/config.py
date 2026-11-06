import os


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://ledgerline:ledgerline@localhost:5432/ledgerline")
SESSION_COOKIE = "__Host-ledgerline" if os.getenv("APP_ENV") == "production" else "ledgerline_session"
SESSION_TTL_HOURS = 12
SECURE_COOKIES = os.getenv("APP_ENV", "development") == "production"
MIGRATION_DATABASE_URL = os.getenv("MIGRATION_DATABASE_URL", DATABASE_URL)
