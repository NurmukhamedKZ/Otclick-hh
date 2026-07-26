#!/bin/sh
# Runs after the image's own migrate.sh (alphabetically "zz-" > "migrate.sh",
# so Supabase's roles/auth/storage schemas already exist by the time this
# runs — our app migrations FK into auth.users).
#
# Reads *.sql from a separately mounted source dir instead of copying files
# into /docker-entrypoint-initdb.d/ at runtime: Postgres's entrypoint expands
# /docker-entrypoint-initdb.d/* via a single shell glob before running any
# script, so files created here mid-run would never be picked up.
set -e

for f in /migrations-src/*.sql; do
    echo "running $f"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$f"
done
