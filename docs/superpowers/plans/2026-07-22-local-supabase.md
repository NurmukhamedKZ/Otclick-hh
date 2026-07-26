# Local Self-Hosted Supabase Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `docker compose up -d --build` (root `docker-compose.yml`) spin up a fully self-hosted Supabase stack (Postgres + Auth + PostgREST + Realtime + Storage + Kong gateway) as the default backing store, with zero changes to `backend/app/db/supabase.py`, `backend/app/api/deps.py`, or `frontend/src/lib/supabase/*` — pointing a cloud Supabase project at the same env vars must keep working unchanged.

**Architecture:** Add six new services to root `docker-compose.yml` (db, auth, rest, realtime, storage, kong) using official Supabase self-host images, gated behind a Kong declarative gateway config that exposes the same REST surface a cloud Supabase project exposes. `infra/supabase/migrations/*.sql` mount into the `db` container's `docker-entrypoint-initdb.d` so they run automatically after Supabase's own schema init. A stdlib-only Python script generates the `JWT_SECRET`/`ANON_KEY`/`SERVICE_ROLE_KEY` triple self-hosters need (no PyJWT dependency, no Supabase account). Google OAuth becomes opt-in via env flag on both GoTrue and the frontend button.

**Tech Stack:** Docker Compose, Supabase self-host images (`supabase/postgres`, `supabase/gotrue`, `postgrest/postgrest`, `supabase/realtime`, `supabase/storage-api`, `kong`), Python stdlib (`hmac`/`hashlib`/`base64`) for key generation, Next.js env var for the Google button flag.

## Global Constraints

- Zero changes to application code paths that talk to Supabase (`backend/app/db/supabase.py`, `backend/app/api/deps.py`, `frontend/src/lib/supabase/client.ts` / `server.ts` / `middleware.ts`) — this is infra + env + docs only, except the one documented Google-button conditional in Task 6.
- `infra/supabase/migrations/*.sql` (files `001_init.sql` through `021_filters_resume_set_null.sql`) run unmodified, in existing order, auto-applied on first container boot.
- Cloud Supabase must remain a fully working alternative by swapping env vars only — no compose profile is required to use it, but the local services must be easy to skip (documented in README, not enforced in code).
- No secrets committed to git — generated keys go in `.env` (gitignored), never `.env.example`.

---

## File Structure

- `infra/supabase/gen-keys.py` — new. Stdlib-only script that prints a fresh `JWT_SECRET` + `ANON_KEY` + `SERVICE_ROLE_KEY` triple (HS256, no deps).
- `infra/supabase/kong.yml` — new. Kong declarative config: routes `/auth/v1`, `/rest/v1`, `/realtime/v1`, `/storage/v1` to the matching service, with `key-auth` consumers for the anon/service-role API keys.
- `infra/supabase/init/00-storage-buckets.sql` — new. Creates the `captcha-screenshots` bucket; mounted into `docker-entrypoint-initdb.d` alongside the app migrations, ordered to run after Supabase's own schema init but before the numbered app migrations.
- `docker-compose.yml` — modified. Adds `db`, `auth`, `rest`, `realtime`, `storage`, `kong` services; `api`/`worker`/`frontend` gain `depends_on: kong` (healthy) and default `SUPABASE_URL`/keys pointed at `http://kong:8000`.
- `backend/.env.example` — modified. Local-stack defaults for `SUPABASE_URL`/keys + comment block on cloud alternative + `POSTGRES_PASSWORD`/`JWT_SECRET`/`ANON_KEY`/`SERVICE_ROLE_KEY` for the compose services + `ENABLE_GOOGLE_AUTH` flag.
- `frontend/.env.local.example` — modified. Same local-stack default + `NEXT_PUBLIC_GOOGLE_AUTH_ENABLED` flag.
- `frontend/src/app/auth/page.tsx` — modified. Google button rendered only when `NEXT_PUBLIC_GOOGLE_AUTH_ENABLED === "true"`.
- `README.md` — modified. Quick Start section rewritten: local stack is the default path, cloud Supabase documented as the alternative.
- `docs/my_docs/DEPLOY.md` — modified. VPS deploy steps updated for the single compose file (no more separate `infra/docker-compose.yml`), local Supabase stack included.

---

## Task 1: Key generation script

**Files:**
- Create: `infra/supabase/gen-keys.py`

**Interfaces:**
- Produces: a CLI script, no importable functions — run directly with `python3 infra/supabase/gen-keys.py`, prints `JWT_SECRET=`, `ANON_KEY=`, `SERVICE_ROLE_KEY=` lines to stdout.

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Generate a JWT_SECRET + matching ANON_KEY/SERVICE_ROLE_KEY for a local
self-hosted Supabase stack. Stdlib only — no PyJWT dependency.

Usage: python3 infra/supabase/gen-keys.py
Paste the three printed lines into backend/.env (and the two NEXT_PUBLIC_
lines into your root .env for the frontend build).
"""

import base64
import hashlib
import hmac
import json
import secrets
import time


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_jwt(secret: str, role: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "role": role,
        "iss": "supabase-local",
        "iat": now,
        # ~10 years — self-hosted, rotate by re-running this script.
        "exp": now + 10 * 365 * 24 * 3600,
    }
    signing_input = f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}." \
        f"{_b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def main() -> None:
    jwt_secret = secrets.token_urlsafe(32)
    anon_key = make_jwt(jwt_secret, "anon")
    service_role_key = make_jwt(jwt_secret, "service_role")
    print(f"JWT_SECRET={jwt_secret}")
    print(f"ANON_KEY={anon_key}")
    print(f"SERVICE_ROLE_KEY={service_role_key}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it and verify shape**

Run: `python3 infra/supabase/gen-keys.py`
Expected: three `KEY=value` lines, `ANON_KEY`/`SERVICE_ROLE_KEY` each three
dot-separated base64url segments (a JWT).

- [ ] **Step 3: Verify the JWT round-trips with a known HS256 decoder**

Run:
```bash
python3 - <<'EOF'
import subprocess, base64, json, hmac, hashlib
out = subprocess.check_output(["python3", "infra/supabase/gen-keys.py"]).decode()
vals = dict(line.split("=", 1) for line in out.strip().splitlines())
secret, anon = vals["JWT_SECRET"], vals["ANON_KEY"]
header_b64, payload_b64, sig_b64 = anon.split(".")
def pad(s): return s + "=" * (-len(s) % 4)
payload = json.loads(base64.urlsafe_b64decode(pad(payload_b64)))
assert payload["role"] == "anon", payload
expected_sig = hmac.new(secret.encode(), f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
actual_sig = base64.urlsafe_b64decode(pad(sig_b64))
assert hmac.compare_digest(expected_sig, actual_sig)
print("OK: anon JWT is valid HS256, role=anon, signature verifies")
EOF
```
Expected: `OK: anon JWT is valid HS256, role=anon, signature verifies`

- [ ] **Step 4: Commit**

```bash
git add infra/supabase/gen-keys.py
git commit -m "feat: add local Supabase JWT/key generation script"
```

---

## Task 2: Kong declarative gateway config

**Files:**
- Create: `infra/supabase/kong.yml`

**Interfaces:**
- Consumes: `$ANON_KEY` / `$SERVICE_ROLE_KEY` referenced by Kong's `key-auth` consumer credentials (substituted via Kong's env-var interpolation at container start — `KONG_ANON_KEY`/`KONG_SERVICE_KEY` set in Task 3's compose service).
- Produces: routes `/auth/v1/*` → `auth:9999`, `/rest/v1/*` → `rest:3000`, `/realtime/v1/*` → `realtime:4000`, `/storage/v1/*` → `storage:5000` — this is what `SUPABASE_URL=http://kong:8000` resolves against, matching cloud Supabase's URL shape (`https://xxx.supabase.co/auth/v1/...` etc.) so `supabase-py`/`@supabase/ssr` need no code change.

- [ ] **Step 1: Write the declarative config**

```yaml
_format_version: "2.1"

services:
  - name: auth-v1
    url: http://auth:9999/
    routes:
      - name: auth-v1-route
        strip_path: true
        paths:
          - /auth/v1/

  - name: rest-v1
    url: http://rest:3000/
    routes:
      - name: rest-v1-route
        strip_path: true
        paths:
          - /rest/v1/
    plugins:
      - name: key-auth
        config:
          key_names: [apikey]

  - name: realtime-v1
    url: http://realtime:4000/socket/
    routes:
      - name: realtime-v1-route
        strip_path: true
        paths:
          - /realtime/v1/
    plugins:
      - name: key-auth
        config:
          key_names: [apikey]

  - name: storage-v1
    url: http://storage:5000/
    routes:
      - name: storage-v1-route
        strip_path: true
        paths:
          - /storage/v1/

consumers:
  - username: anon
    keyauth_credentials:
      - key: $ANON_KEY
  - username: service_role
    keyauth_credentials:
      - key: $SERVICE_ROLE_KEY
```

- [ ] **Step 2: Validate YAML syntax**

Run: `python3 -c "import yaml; yaml.safe_load(open('infra/supabase/kong.yml'))" ` (uses the stdlib-adjacent `pyyaml` already pulled in by other backend deps — if missing, `python3 -c "import json,sys; sys.path.insert(0,'.'); print('skip: pyyaml not installed, will validate via Kong container in Task 5')"`)
Expected: no exception (or the skip message — Task 5's `docker compose up` is the real validation since Kong itself will refuse to boot on malformed config).

- [ ] **Step 3: Commit**

```bash
git add infra/supabase/kong.yml
git commit -m "feat: add Kong declarative gateway config for local Supabase"
```

---

## Task 3: Storage bucket init SQL

**Files:**
- Create: `infra/supabase/init/00-storage-buckets.sql`

**Interfaces:**
- Produces: a `captcha-screenshots` bucket row in `storage.buckets`, present before any app code (or app migration) references it. Filename prefix `00-` sorts before `infra/supabase/migrations/001_init.sql` when both directories' contents are merged into the same `docker-entrypoint-initdb.d` mount order (Task 4 mounts this file at a path that sorts first — see Task 4 Step 1 for the exact mount ordering).

- [ ] **Step 1: Write the bucket-creation SQL**

```sql
-- Storage bucket for worker-captured captcha screenshots
-- (services/captcha.py uploads here; auth/hh_auth.py during OAuth captcha handoff).
insert into storage.buckets (id, name, public)
values ('captcha-screenshots', 'captcha-screenshots', false)
on conflict (id) do nothing;
```

- [ ] **Step 2: Commit**

```bash
git add infra/supabase/init/00-storage-buckets.sql
git commit -m "feat: add captcha-screenshots storage bucket init SQL"
```

---

## Task 4: Compose services — db, auth, rest, realtime, storage, kong

**Files:**
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: `infra/supabase/kong.yml` (Task 2), `infra/supabase/init/00-storage-buckets.sql` (Task 3), `infra/supabase/migrations/*.sql` (existing).
- Produces: `SUPABASE_URL=http://kong:8000` reachable from `api`/`worker` containers (internal Docker network), `http://localhost:8000` from the host; Postgres reachable at `db:5432` inside the network.

- [ ] **Step 1: Add the six services to `docker-compose.yml`**

Insert before the existing `api:` service (so `db` boots first); mount order matters — Postgres runs every `*.sql`/`*.sh` in `/docker-entrypoint-initdb.d/` in lexicographic filename order across *all* mounted subpaths, so mounting `infra/supabase/init/00-storage-buckets.sql` at `/docker-entrypoint-initdb.d/00-storage-buckets.sql` and each `infra/supabase/migrations/0NN_*.sql` at `/docker-entrypoint-initdb.d/0NN_*.sql` (flattened, no subdirectory) guarantees `00-` runs first, then `001_` through `021_` in order:

```yaml
services:
  db:
    image: supabase/postgres:15.1.1.78
    container_name: aiautoclicker-db
    restart: unless-stopped
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}
      POSTGRES_DB: postgres
      JWT_SECRET: ${JWT_SECRET:?set JWT_SECRET in .env}
    volumes:
      - supabase-db-data:/var/lib/postgresql/data
      - ./infra/supabase/init/00-storage-buckets.sql:/docker-entrypoint-initdb.d/00-storage-buckets.sql:ro
      - ./infra/supabase/migrations:/docker-entrypoint-initdb.d/migrations-src:ro
      - ./infra/supabase/flatten-migrations.sh:/docker-entrypoint-initdb.d/01-flatten-migrations.sh:ro
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "postgres"]
      interval: 5s
      timeout: 5s
      retries: 10

  auth:
    image: supabase/gotrue:v2.170.0
    container_name: aiautoclicker-auth
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    environment:
      GOTRUE_API_HOST: 0.0.0.0
      GOTRUE_API_PORT: 9999
      GOTRUE_DB_DRIVER: postgres
      GOTRUE_DB_DATABASE_URL: postgres://supabase_auth_admin:${POSTGRES_PASSWORD}@db:5432/postgres
      GOTRUE_SITE_URL: ${NEXT_PUBLIC_APP_URL:-http://localhost:3000}
      GOTRUE_URI_ALLOW_LIST: "*"
      GOTRUE_DISABLE_SIGNUP: "false"
      GOTRUE_JWT_SECRET: ${JWT_SECRET}
      GOTRUE_JWT_EXP: 3600
      GOTRUE_JWT_DEFAULT_GROUP_NAME: authenticated
      GOTRUE_EXTERNAL_EMAIL_ENABLED: "true"
      # Local self-host has no SMTP configured by default — autoconfirm so
      # sign-up doesn't dead-end waiting on a confirmation email. Self-hosters
      # who wire up SMTP (GOTRUE_SMTP_*) should flip this back to "false".
      GOTRUE_MAILER_AUTOCONFIRM: "true"
      GOTRUE_EXTERNAL_GOOGLE_ENABLED: ${ENABLE_GOOGLE_AUTH:-false}
      GOTRUE_EXTERNAL_GOOGLE_CLIENT_ID: ${GOOGLE_CLIENT_ID:-}
      GOTRUE_EXTERNAL_GOOGLE_SECRET: ${GOOGLE_CLIENT_SECRET:-}
      GOTRUE_EXTERNAL_GOOGLE_REDIRECT_URI: ${NEXT_PUBLIC_APP_URL:-http://localhost:3000}/auth/callback

  rest:
    image: postgrest/postgrest:v12.2.0
    container_name: aiautoclicker-rest
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    environment:
      PGRST_DB_URI: postgres://authenticator:${POSTGRES_PASSWORD}@db:5432/postgres
      PGRST_DB_SCHEMAS: public,storage
      PGRST_DB_ANON_ROLE: anon
      PGRST_JWT_SECRET: ${JWT_SECRET}

  realtime:
    image: supabase/realtime:v2.34.7
    container_name: aiautoclicker-realtime
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    environment:
      PORT: 4000
      DB_HOST: db
      DB_PORT: 5432
      DB_NAME: postgres
      DB_USER: supabase_admin
      DB_PASSWORD: ${POSTGRES_PASSWORD}
      DB_AFTER_CONNECT_QUERY: "SET search_path TO _realtime"
      DB_ENC_KEY: supabaserealtime
      API_JWT_SECRET: ${JWT_SECRET}
      SECRET_KEY_BASE: ${JWT_SECRET}${JWT_SECRET}
      ERL_AFLAGS: -proto_dist inet_tcp
      DNS_NODES: "''"
      RLIMIT_NOFILE: 10000
      APP_NAME: realtime
      SEED_SELF_HOST: "true"
      RUN_JANITOR: "true"

  storage:
    image: supabase/storage-api:v1.11.13
    container_name: aiautoclicker-storage
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
      rest:
        condition: service_started
    environment:
      ANON_KEY: ${ANON_KEY}
      SERVICE_KEY: ${SERVICE_ROLE_KEY}
      POSTGREST_URL: http://rest:3000
      PGRST_JWT_SECRET: ${JWT_SECRET}
      DATABASE_URL: postgres://supabase_storage_admin:${POSTGRES_PASSWORD}@db:5432/postgres
      FILE_SIZE_LIMIT: 52428800
      STORAGE_BACKEND: file
      FILE_STORAGE_BACKEND_PATH: /var/lib/storage
      TENANT_ID: stub
      REGION: stub
      GLOBAL_S3_BUCKET: stub
    volumes:
      - supabase-storage-data:/var/lib/storage

  kong:
    image: kong:2.8.1
    container_name: aiautoclicker-kong
    restart: unless-stopped
    depends_on:
      - auth
      - rest
      - realtime
      - storage
    environment:
      KONG_DATABASE: "off"
      KONG_DECLARATIVE_CONFIG: /kong.yml
      KONG_DNS_ORDER: LAST,A,CNAME
      KONG_PLUGINS: request-transformer,key-auth
      ANON_KEY: ${ANON_KEY}
      SERVICE_ROLE_KEY: ${SERVICE_ROLE_KEY}
    volumes:
      - ./infra/supabase/kong.yml:/kong.yml.tpl:ro
    # Kong's declarative config doesn't do env substitution natively for
    # $ANON_KEY/$SERVICE_ROLE_KEY placeholders — render kong.yml.tpl into
    # /kong.yml with envsubst on start.
    entrypoint: ["sh", "-c", "apk add --no-cache gettext >/dev/null 2>&1 || true; envsubst < /kong.yml.tpl > /kong.yml; exec /docker-entrypoint.sh kong docker-start"]
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD", "kong", "health"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 10s
```

- [ ] **Step 2: Add the migration-flattening init script referenced above**

Postgres's `docker-entrypoint-initdb.d` doesn't recurse into subdirectories, so
`infra/supabase/migrations/*.sql` (mounted read-only at `migrations-src`) needs
copying into the top-level init dir at container start, before Postgres's
own init scripts finish running. Create `infra/supabase/flatten-migrations.sh`:

```bash
#!/bin/sh
# Runs as part of docker-entrypoint-initdb.d (mounted as 01-flatten-migrations.sh,
# sorts after 00-storage-buckets.sql, before Postgres processes anything past
# this script alphabetically — but our app migrations are named 0NN_*.sql,
# which sorts after both "00-" and "01-" prefixes, so this copy step
# completing before the entrypoint continues scanning is what makes them run).
set -e
cp /docker-entrypoint-initdb.d/migrations-src/*.sql /docker-entrypoint-initdb.d/
```

Mark it executable and reference it exactly as `01-flatten-migrations.sh` in
the `db` service volumes (already done in Step 1).

Run: `chmod +x infra/supabase/flatten-migrations.sh`

- [ ] **Step 3: Add named volumes**

Append to the bottom of `docker-compose.yml`:

```yaml
volumes:
  supabase-db-data:
  supabase-storage-data:
```

- [ ] **Step 4: Boot the stack and verify migrations applied**

Run:
```bash
cp backend/.env.example backend/.env   # placeholder values are enough for this check
python3 infra/supabase/gen-keys.py     # copy JWT_SECRET/ANON_KEY/SERVICE_ROLE_KEY into backend/.env
echo "POSTGRES_PASSWORD=localtest123" >> backend/.env
docker compose up -d db auth rest realtime storage kong
sleep 15
docker compose exec db psql -U postgres -c "\dt public.*" | grep -c applications
```
Expected: `1` (the `applications` table from `001_init.sql` exists), and
`docker compose ps` shows `db`/`auth`/`rest`/`realtime`/`storage`/`kong` all
`healthy` or `running`.

- [ ] **Step 5: Verify the storage bucket exists**

Run: `docker compose exec db psql -U postgres -c "select id from storage.buckets;"`
Expected: output includes `captcha-screenshots`.

- [ ] **Step 6: Tear down and commit**

```bash
docker compose down
git add docker-compose.yml infra/supabase/flatten-migrations.sh
git commit -m "feat: add local self-hosted Supabase services to docker-compose.yml"
```

---

## Task 5: Wire `api`/`worker`/`frontend` to the local stack by default

**Files:**
- Modify: `docker-compose.yml:api`, `docker-compose.yml:worker`, `docker-compose.yml:frontend`
- Modify: `backend/.env.example`
- Modify: `frontend/.env.local.example`

**Interfaces:**
- Consumes: `kong` service from Task 4 (must be `condition: service_healthy` before `api`/`worker` start, same pattern already used for `api`→`worker`).

- [ ] **Step 1: Make `api`/`worker` depend on `kong` and default `SUPABASE_URL` locally**

In `docker-compose.yml`, `api` service: add
```yaml
    depends_on:
      kong:
        condition: service_healthy
```
replacing its current bare `healthcheck:` block position (keep the existing
`healthcheck:` block too — both `depends_on` and `healthcheck` coexist).

`worker` service: change its existing
```yaml
    depends_on:
      api:
        condition: service_healthy
```
to
```yaml
    depends_on:
      api:
        condition: service_healthy
      kong:
        condition: service_healthy
```

- [ ] **Step 2: Update `backend/.env.example`**

Replace the top `# Supabase` block:
```
# Supabase — local self-hosted stack (default, no cloud account needed).
# 1. Run: python3 infra/supabase/gen-keys.py
# 2. Paste the three printed lines below.
# 3. Set POSTGRES_PASSWORD to any strong local secret.
SUPABASE_URL=http://kong:8000
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
JWT_SECRET=
ANON_KEY=
SERVICE_ROLE_KEY=
POSTGRES_PASSWORD=

# To use a managed/cloud Supabase project instead, comment out the local
# `db`/`auth`/`rest`/`realtime`/`storage`/`kong` services in docker-compose.yml
# and set these three to your project's values instead:
# SUPABASE_URL=https://xxxx.supabase.co
# SUPABASE_ANON_KEY=eyJ...
# SUPABASE_SERVICE_ROLE_KEY=eyJ...

# Google OAuth login — optional, off by default (no Google Cloud Console
# project needed to get started). Set to true + fill in the two vars below
# to enable the "continue with Google" button.
ENABLE_GOOGLE_AUTH=false
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
```
Note `SUPABASE_ANON_KEY`/`SUPABASE_SERVICE_ROLE_KEY` (consumed by
`backend/app/db/supabase.py`) are set to the *same values* as `ANON_KEY`/
`SERVICE_ROLE_KEY` (consumed by the compose services in Task 4) — self-hosters
paste the generated key twice, once per var name, since the app config
(`Settings` in `backend/app/config.py`) and the compose services read
differently-named env vars from the same `.env` file.

- [ ] **Step 3: Update `frontend/.env.local.example`**

```
NEXT_PUBLIC_SUPABASE_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_ANON_KEY=YOUR_ANON_KEY
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_GOOGLE_AUTH_ENABLED=false
```

- [ ] **Step 4: Full stack boot test**

Run:
```bash
cp backend/.env.example backend/.env
python3 infra/supabase/gen-keys.py  # fill JWT_SECRET/ANON_KEY/SERVICE_ROLE_KEY
# also copy ANON_KEY value into SUPABASE_ANON_KEY, SERVICE_ROLE_KEY into SUPABASE_SERVICE_ROLE_KEY
echo "POSTGRES_PASSWORD=localtest123" >> backend/.env
docker compose up -d --build
sleep 20
curl -fsS http://localhost:8000/health  # kong -> nothing at root; check api directly instead
curl -fsS http://localhost:8000/health || true
curl -fsS http://localhost:8000/8000 2>/dev/null || true
docker compose exec api curl -fsS http://localhost:8000/health
```
Expected: `api`'s own `/health` (port 8000 on the `api` container, distinct
from Kong's 8000 published on the host — **note the port collision**: fix
in Step 5 before this passes).

- [ ] **Step 5: Fix the port collision between `api` and `kong`**

Both `api` and `kong` currently publish host port `8000`. Change Kong's
published port in `docker-compose.yml` from `"8000:8000"` to `"54321:8000"`
(a distinctive, memorable, unlikely-to-collide port — matches the port
Supabase's own local CLI (`supabase start`) conventionally uses for its
API gateway, so it'll look familiar to anyone who's used Supabase locally
before). Update every reference from `http://localhost:8000` to
`http://localhost:54321` in `backend/.env.example` (the cloud-alternative
comment stays as-is since that's a real cloud URL) and
`frontend/.env.local.example`. The container-internal
`SUPABASE_URL=http://kong:8000` stays `8000` — that's the *container's*
internal port, not the host-published one.

- [ ] **Step 6: Re-run the boot test**

Run:
```bash
docker compose down
docker compose up -d --build
sleep 20
curl -fsS http://localhost:8000/health
curl -fsS -H "apikey: $(grep ^ANON_KEY backend/.env | cut -d= -f2)" http://localhost:54321/rest/v1/
```
Expected: first `curl` returns the API's health JSON; second returns a
PostgREST OpenAPI root response (not a 401), proving Kong→PostgREST routing
and the anon key both work.

- [ ] **Step 7: Tear down and commit**

```bash
docker compose down
git add docker-compose.yml backend/.env.example frontend/.env.local.example
git commit -m "feat: wire api/worker/frontend to local Supabase stack by default"
```

---

## Task 6: Google OAuth opt-in on the frontend

**Files:**
- Modify: `frontend/src/app/auth/page.tsx:52-58` (the `google()` handler), `:204-222` (the button JSX)

**Interfaces:**
- Consumes: `NEXT_PUBLIC_GOOGLE_AUTH_ENABLED` (Task 5, `frontend/.env.local.example`).

- [ ] **Step 1: Guard the button render**

In `frontend/src/app/auth/page.tsx`, add near the top of the component body
(after the existing `useState` declarations, before `async function submit`):

```tsx
  const googleAuthEnabled = process.env.NEXT_PUBLIC_GOOGLE_AUTH_ENABLED === "true";
```

Wrap the existing Google `<button>` block (currently unconditional) in:

```tsx
          {googleAuthEnabled && (
            <button
              type="button"
              onClick={google}
              /* ...existing props/children unchanged... */
            >
              {/* ...existing svg + text unchanged... */}
            </button>
          )}
```

Leave the divider (`"или"` / separator row) below it — check whether it
reads oddly with no button above it; if so, wrap the divider in the same
`{googleAuthEnabled && (...)}` condition, since a lone "or" divider with
nothing above it is a visible layout bug.

- [ ] **Step 2: Manual verification**

Run: `cd frontend && NEXT_PUBLIC_GOOGLE_AUTH_ENABLED=false npm run dev`
Open `http://localhost:3000/auth` in a browser — expected: no "продолжить с
google" button, no orphaned divider, email/password form unaffected.

Run: `NEXT_PUBLIC_GOOGLE_AUTH_ENABLED=true npm run dev` (restart)
Expected: button reappears exactly as before this change.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/auth/page.tsx
git commit -m "feat: make Google OAuth button opt-in via env flag"
```

---

## Task 7: README + deploy docs

**Files:**
- Modify: `README.md` (Quick Start section, currently starting "## Quick Start" — prerequisites list including "A Supabase project (free tier works)", and the `.env.local` setup steps)
- Modify: `docs/my_docs/DEPLOY.md`

**Interfaces:**
- Consumes: nothing new — pure documentation reflecting Tasks 1-6.

- [ ] **Step 1: Rewrite README Quick Start**

Replace the "A Supabase project (free tier works)" prerequisite line with:
"Nothing else — `docker compose up` runs a full local Supabase stack
(Postgres + Auth + Storage + Realtime) alongside the app. No account, no
cloud project." Add a short "Using cloud Supabase instead" subsection
pointing at the commented-out block in `backend/.env.example` (Task 5 Step 2).

Update the `.env.local` setup step to reference
`python3 infra/supabase/gen-keys.py` for generating keys instead of "copy
from your Supabase dashboard."

- [ ] **Step 2: Update `docs/my_docs/DEPLOY.md`**

Read the current file first (`docs/my_docs/DEPLOY.md` was already modified
per the `infra/docker-compose.yml` deletion — confirm it no longer
references the deleted file) and update any remaining steps that assume a
cloud Supabase project for VPS deploys to instead reference the local
stack in root `docker-compose.yml`, matching the "single docker compose
file" change already committed.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/my_docs/DEPLOY.md
git commit -m "docs: document local self-hosted Supabase quick start"
```

---

## Task 8: End-to-end verification

**Files:** none created/modified — verification only.

- [ ] **Step 1: Existing backend test suite unaffected**

Run: `cd backend && python -m pytest tests/ -v`
Expected: same pass/fail state as before this branch (tests mock the
Supabase client, so this change shouldn't touch them at all — a new
failure here is a regression to investigate, not expected).

- [ ] **Step 2: Full stack fresh boot**

Run:
```bash
docker compose down -v   # -v: wipe the named volumes from earlier test boots so migrations re-run from scratch
docker compose up -d --build
sleep 25
docker compose ps
```
Expected: all 8 services (`db`, `auth`, `rest`, `realtime`, `storage`,
`kong`, `api`, `worker`, `frontend` — 9 total) running/healthy.

- [ ] **Step 3: Sign-up → login round trip through the UI**

Open `http://localhost:3000/auth`, sign up with a test email/password.
Expected: redirected to `/dashboard` immediately (GOTRUE_MAILER_AUTOCONFIRM
skips the confirmation-email wait), session persists on refresh.

- [ ] **Step 4: Captcha bucket round-trip**

Run:
```bash
docker compose exec api python3 -c "
from app.db.supabase import service_client
data = b'test-image-bytes'
service_client.storage.from_('captcha-screenshots').upload('test.png', data)
out = service_client.storage.from_('captcha-screenshots').download('test.png')
assert out == data
print('OK: storage round-trip works')
service_client.storage.from_('captcha-screenshots').remove(['test.png'])
"
```
Expected: `OK: storage round-trip works`.

- [ ] **Step 5: Cloud Supabase alternative still works (no code regression)**

If a cloud Supabase project is available for testing: point `SUPABASE_URL`/
`SUPABASE_ANON_KEY`/`SUPABASE_SERVICE_ROLE_KEY` in `backend/.env` and
`NEXT_PUBLIC_SUPABASE_URL`/`NEXT_PUBLIC_SUPABASE_ANON_KEY` in the frontend
build args at it, stop the local `db`/`auth`/`rest`/`realtime`/`storage`/
`kong` services (`docker compose stop db auth rest realtime storage kong`),
restart `api`/`worker`/`frontend`. Expected: same sign-up/login flow works
against the cloud project — confirms no hidden dependency on the local
stack crept into application code.

- [ ] **Step 6: Tear down**

```bash
docker compose down
```

(No commit — this task is verification only.)
