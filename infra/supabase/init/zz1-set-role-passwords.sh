#!/bin/sh
# migrate.sh (the supabase/postgres image's own bootstrap, which runs before
# any "zz*" file alphabetically) only sets a password for supabase_admin.
# Every other operational role it creates (authenticator, supabase_auth_admin,
# supabase_storage_admin) is left with no usable password, so real
# scram-sha-256 auth from other containers on the Docker network fails even
# though local/trust connections inside this container appear to work.
#
# migrate.sh's post-setup step demotes "postgres" from superuser and makes
# supabase_admin the real superuser — connect as supabase_admin, not
# postgres, or ALTER ROLE on these protected roles is refused.
set -e

psql -v ON_ERROR_STOP=1 --username supabase_admin --dbname "$POSTGRES_DB" <<-EOSQL
    ALTER ROLE authenticator WITH PASSWORD '${POSTGRES_PASSWORD}';
    ALTER ROLE supabase_auth_admin WITH PASSWORD '${POSTGRES_PASSWORD}';
    ALTER ROLE supabase_storage_admin WITH PASSWORD '${POSTGRES_PASSWORD}';

    -- Realtime (self-hosted, SEED_SELF_HOST=true) expects this schema to
    -- already exist before its own ecto migrations run — the base image
    -- doesn't create it, only the official self-host stack's separate
    -- realtime.sql init step does.
    CREATE SCHEMA IF NOT EXISTS _realtime;
    GRANT ALL ON SCHEMA _realtime TO supabase_admin;
EOSQL
