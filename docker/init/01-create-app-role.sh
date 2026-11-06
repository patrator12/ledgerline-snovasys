#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=app_password="$LEDGERLINE_APP_PASSWORD" <<'SQL'
CREATE ROLE ledgerline_app LOGIN PASSWORD :'app_password';
SQL
