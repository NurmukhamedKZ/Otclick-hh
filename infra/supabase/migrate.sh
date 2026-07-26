#!/bin/sh
# Applies every infra/supabase/migrations/*.sql that isn't recorded in
# public.schema_migrations yet, each in its own transaction. Idempotent:
# safe to run on every stack start.
#
# Used twice: as the db init hook (fresh volume, zz2-run-app-migrations.sh)
# and as the one-shot `migrate` compose service (existing volume).
#
# Env: psql connection vars (PGHOST/PGUSER/PGPASSWORD/PGDATABASE) or, in the
# init-hook case, the socket defaults + POSTGRES_USER/POSTGRES_DB.
set -e

MIGRATIONS_DIR="${MIGRATIONS_DIR:-/migrations-src}"
PSQL="psql -v ON_ERROR_STOP=1 --username ${PGUSER:-${POSTGRES_USER:-postgres}} --dbname ${PGDATABASE:-${POSTGRES_DB:-postgres}}"

$PSQL -q -c "CREATE TABLE IF NOT EXISTS public.schema_migrations (
  version text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);"

# Pre-runner databases have the schema but no ledger. Adopt them: record every
# migration currently on disk as applied instead of replaying it into a live DB.
# ponytail: assumes such a DB is fully up to date; if you upgraded the code and
# the DB in one step, verify the newest migrations landed (\d, or re-run them
# by hand) — after this one-time baseline the ledger is exact.
applied_count=$($PSQL -tAc "SELECT count(*) FROM public.schema_migrations")
has_schema=$($PSQL -tAc "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename='profiles'")
if [ "$applied_count" = "0" ] && [ "$has_schema" != "0" ]; then
    echo "migrate: existing database without a ledger — baselining as fully applied"
    for f in "$MIGRATIONS_DIR"/*.sql; do
        $PSQL -q -c "INSERT INTO public.schema_migrations (version) VALUES ('$(basename "$f")')"
    done
    echo "migrate: baseline done — verify the newest migrations are really applied"
    exit 0
fi

for f in "$MIGRATIONS_DIR"/*.sql; do
    version=$(basename "$f")
    done_already=$($PSQL -tAc "SELECT 1 FROM public.schema_migrations WHERE version='$version'")
    if [ "$done_already" = "1" ]; then
        continue
    fi
    echo "migrate: applying $version"
    $PSQL -1 -f "$f" -c "INSERT INTO public.schema_migrations (version) VALUES ('$version')"
done
echo "migrate: up to date"
