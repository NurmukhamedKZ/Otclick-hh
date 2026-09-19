#!/bin/sh
# Runs after the image's own migrate.sh (alphabetically "zz-" > "migrate.sh",
# so Supabase's roles/auth/storage schemas already exist by the time this
# runs — our app migrations FK into auth.users).
#
# Fresh volume only (docker-entrypoint-initdb.d runs once). Same script as the
# `migrate` compose service, so both paths record into schema_migrations and
# neither replays what the other already applied.
#
# The script is bind-mounted read-only. Do not exec it directly because the
# executable bit of a bind-mounted host file is not guaranteed on every host.
# Running it explicitly through sh makes fresh installs independent of host
# file-mode metadata.
set -e
exec sh /migrate.sh
