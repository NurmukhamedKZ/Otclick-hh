#!/bin/sh
# Creates the captcha-screenshots bucket. Must run AFTER the storage-api
# service has completed its own internal migrations (it adds columns like
# `public` to storage.buckets that don't exist right after the Postgres
# image's own bootstrap) — so this runs as a one-shot service depending on
# `storage`, not as a docker-entrypoint-initdb.d script on `db`.
set -e

until PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 -h db -U supabase_admin -d postgres -c "select 1 from information_schema.columns where table_schema='storage' and table_name='buckets' and column_name='public'" | grep -q "1 row"; do
    echo "waiting for storage-api to finish migrating storage.buckets..."
    sleep 2
done

PGPASSWORD="$POSTGRES_PASSWORD" psql -v ON_ERROR_STOP=1 -h db -U supabase_admin -d postgres -c "
insert into storage.buckets (id, name, public)
values ('captcha-screenshots', 'captcha-screenshots', false)
on conflict (id) do nothing;
"
echo "captcha-screenshots bucket ready"
