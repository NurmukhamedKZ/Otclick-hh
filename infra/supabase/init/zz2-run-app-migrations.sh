#!/bin/sh
# Runs after the image's own migrate.sh (alphabetically "zz-" > "migrate.sh",
# so Supabase's roles/auth/storage schemas already exist by the time this
# runs — our app migrations FK into auth.users).
#
# Fresh volume only (docker-entrypoint-initdb.d runs once). Same script as the
# `migrate` compose service, so both paths record into schema_migrations and
# neither replays what the other already applied.
set -e
exec /migrate.sh
