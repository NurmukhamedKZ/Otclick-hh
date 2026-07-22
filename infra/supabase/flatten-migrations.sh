#!/bin/sh
# Runs as part of docker-entrypoint-initdb.d (mounted as 01-flatten-migrations.sh,
# sorts after 00-storage-buckets.sql, before Postgres processes anything past
# this script alphabetically — but our app migrations are named 0NN_*.sql,
# which sorts after both "00-" and "01-" prefixes, so this copy step
# completing before the entrypoint continues scanning is what makes them run).
set -e
cp /docker-entrypoint-initdb.d/migrations-src/*.sql /docker-entrypoint-initdb.d/
