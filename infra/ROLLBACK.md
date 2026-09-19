# Otclick-hh — rollback after a failed update

`install.sh` creates a PostgreSQL dump **before** pulling a newer revision whenever an existing installation is updated. It also copies the current `.env` into the same `backups/` directory.

The installer intentionally does not roll the database back automatically: SQL migrations can be forward-only, and an automatic partial restore is more dangerous than stopping with the exact backup path in the log.

## 1. Stop application services

From the installation directory (default `/opt/otclick-hh`):

```bash
cd /opt/otclick-hh
docker compose stop caddy frontend worker api auth rest realtime storage kong
```

Keep `db` running.

## 2. Restore the previous code revision

The failed installer prints `Previous git revision: <SHA>`.

```bash
git reset --hard <PREVIOUS_SHA>
```

Do not replace `.env` with `.env.example`. The installer preserves the existing `.env` and stores a timestamped backup copy before updating.

## 3. Restore the database only when required

If the failed update already applied migrations, use the PostgreSQL dump printed by the installer as `Database backup: ...`.

Before overwriting the current database, create one more safety dump:

```bash
mkdir -p backups
docker compose exec -T db pg_dump -U postgres -d postgres -Fc > backups/pre-rollback-$(date -u +%Y%m%dT%H%M%SZ).dump
chmod 600 backups/pre-rollback-*.dump
```

Then restore the pre-update dump:

```bash
docker compose exec -T db pg_restore \
  -U postgres \
  -d postgres \
  --clean \
  --if-exists \
  --no-owner \
  --exit-on-error \
  < /absolute/path/from/installer/postgres-YYYYMMDDTHHMMSSZ.dump
```

If `pg_restore` reports active-connection conflicts, stop every service except `db` and repeat the restore. Do not delete the Docker volume as part of rollback.

## 4. Rebuild the previous revision

```bash
docker compose up -d --build
```

Check:

```bash
curl -fsS http://127.0.0.1:8000/health
docker compose ps
```

## Safety invariants

Rollback must not change these values in `.env`:

```env
DISABLE_SIGNUP=true
ALLOW_REAL_APPLY=false
```

Do not enable real HH submissions as part of rollback/recovery.
