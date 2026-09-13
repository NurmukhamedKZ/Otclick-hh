<p align="center">
  <img src="https://raw.githubusercontent.com/gest0r1/Otclick-hh/main/docs/assets/banner.svg" alt="Otclick" width="100%"/>
</p>

<h1 align="center">Otclick 🤖</h1>

<p align="center">
  <strong>Self-hosted AI-assisted job application automation for hh.ru / hh.kz</strong>
</p>

> Active fork: `gest0r1/Otclick-hh`. Production install/update tracks this repository's `main` branch.

---

## Quick Start

### Production requirements

- Ubuntu/Linux amd64;
- `bash`, `git`, `curl`, Python 3, `gzip`, `sha256sum`;
- Docker Engine with Docker Compose v2 (`docker compose`).

`zstd` is needed only if anonymous GHCR access is unavailable and the updater has to use a per-component GitHub Release fallback. On Debian/Ubuntu the updater installs it automatically when that fallback is actually needed.

### Install or update — one command

Use the same command for the first installation and every later update:

```bash
curl -fsSL https://raw.githubusercontent.com/gest0r1/Otclick-hh/main/install.sh | bash
```

The canonical production directory is:

```text
/opt/otclick-hh
```

The command has two deliberately different paths:

**Fresh install**

1. clones `main` into `/opt/otclick-hh`;
2. creates `.env` only when no existing Otclick database is detected;
3. waits for the exact-SHA GitHub Actions release;
4. downloads the combined prebuilt backend/frontend bundle once;
5. verifies checksums and starts the stack with `--no-build`.

**Existing installation / normal update**

1. immediately delegates to `install-update.sh` before any combined bundle is downloaded;
2. preserves the existing `.env`, PostgreSQL volumes, accounts, tokens and encrypted HH credentials;
3. fetches only the small exact-SHA `manifest.json` + checksum metadata;
4. compares content hashes for backend, frontend, Compose, infra and migrations;
5. pulls only changed backend/frontend components from public GHCR by immutable digest, reusing Docker layers;
6. downloads **0 application bytes** for unchanged components;
7. uses a per-component GitHub Release archive only as a fallback if GHCR is unavailable;
8. backs up PostgreSQL before schema changes, runs idempotent migrations and reconciles the stack with `--no-build`.

The updater also refuses to continue if `/opt/otclick-hh/.env` is missing. It never generates replacement PostgreSQL/JWT/Fernet secrets for an existing installation.

### Production build and transport policy

**Production installation/update never builds backend or frontend on the server.**

Application images are built by `.github/workflows/build-artifact.yml` in GitHub Actions. Backend and frontend are published as immutable content-addressed GHCR images. Every Git commit also receives an exact-SHA v2 manifest release:

```text
install-<git-sha>
```

Normal update path:

```text
GitHub main
    │
    ├── tiny exact-SHA v2 manifest
    │
    ├── changed backend ──► GHCR immutable image ──► docker pull/layer cache
    └── changed frontend ─► GHCR immutable image ──► docker pull/layer cache
```

The large combined release asset exists only for a fresh installation. An existing installation must never download it.

If the exact manifest or required image is not available, the installer fails. It does **not** silently fall back to `docker compose build`.

```text
Development machine: source -> local build/test -> GitHub
Production server:    GitHub exact commit -> changed prebuilt layers -> run/test
```

### Existing installation

The update command remains exactly the same:

```bash
curl -fsSL https://raw.githubusercontent.com/gest0r1/Otclick-hh/main/install.sh | bash
```

Do not run:

```bash
python3 infra/bootstrap.py --force
```

on an existing installation. It rotates PostgreSQL/JWT/Fernet secrets and can invalidate sessions or make stored encrypted HH credentials unreadable.

### Explicit installation directory

`/opt/otclick-hh` is the supported default. An override is available when deliberately needed:

```bash
curl -fsSL https://raw.githubusercontent.com/gest0r1/Otclick-hh/main/install.sh | bash -s -- /some/other/path
```

---

## What it does

Otclick automates routine parts of working with hh.ru/hh.kz while keeping user-controlled actions visible in the web interface.

- Vacancy search, saved filters, deduplication and exclusions.
- Optional AI relevance screening.
- Vacancy-specific cover letters generated from the resume and vacancy.
- Background apply worker with throttling, limits and retries.
- Draft answers for vacancy forms/tests.
- Recruiter conversation support and todo flow.
- Captcha handoff for manual handling.
- Application analytics and negotiation state.
- Employer blacklist.
- Firefox extension for assisted external forms.
- Self-hosted Supabase: PostgreSQL, Auth, Realtime and Storage.

---

## Architecture

```text
Browser / phone
      │
      ▼
Next.js frontend
      │ JWT
      ▼
FastAPI API ───────────────► hh.ru / hh.kz / chatik.hh.ru
      │
      ├────────► PostgreSQL / Supabase Auth / Realtime / Storage
      │
      └────────► OpenAI-compatible LLM endpoint (optional)

Background worker ─────────► search / relevance / apply / recruiter polling
```

Production deployment uses:

```text
docker-compose.yml
+ docker-compose.prebuilt.yml
```

`docker-compose.prebuilt.yml` supplies runtime frontend configuration for the generic prebuilt Next.js image. `NEXT_PUBLIC_*` values are inserted when the container starts instead of being permanently tied to CI values.

---

## Configuration

The canonical environment file is:

```text
/opt/otclick-hh/.env
```

`infra/bootstrap.py` generates secrets only for a fresh installation. Back this file up securely, especially `FERNET_KEY`.

Important generated secrets include:

- `POSTGRES_PASSWORD`;
- `JWT_SECRET`;
- `ANON_KEY` / `SUPABASE_ANON_KEY`;
- `SERVICE_ROLE_KEY` / `SUPABASE_SERVICE_ROLE_KEY`;
- `FERNET_KEY`;
- `INTERNAL_CRON_TOKEN`.

Typical AI settings:

```env
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=...
AI_POSITIONING=balanced
```

Without `OPENAI_API_KEY` the core stack can still start; AI-dependent functions remain unavailable or use their fallback behavior.

---

## Database migrations

SQL migrations live in:

```text
infra/supabase/migrations/
```

The one-shot `migrate` service applies migrations not yet recorded in `public.schema_migrations`.

Check migration output:

```bash
cd /opt/otclick-hh
docker compose -f docker-compose.yml -f docker-compose.prebuilt.yml logs migrate
```

Never delete the database volume during a normal update.

---

## Operations

### Update

```bash
curl -fsSL https://raw.githubusercontent.com/gest0r1/Otclick-hh/main/install.sh | bash
```

An ordinary update should show an incremental path such as:

```text
Existing installation detected ... using incremental updater
[2/7] fetching exact-SHA incremental manifest
[3/7] updating changed application components
backend unchanged; 0 application bytes downloaded
frontend: GHCR pull complete (cached layers reused)
[6/7] reconciling stack without local builds
```

It should **not** show Docker BuildKit steps such as `[api 1/9]`, `[frontend 1/7]`, `docker build`, or a download of the combined ~GiB fresh-install bundle.

### Status

```bash
cd /opt/otclick-hh
docker compose -f docker-compose.yml -f docker-compose.prebuilt.yml ps -a
```

### Logs

```bash
cd /opt/otclick-hh
docker compose -f docker-compose.yml -f docker-compose.prebuilt.yml logs -f --tail=200 api
docker compose -f docker-compose.yml -f docker-compose.prebuilt.yml logs -f --tail=200 worker
docker compose -f docker-compose.yml -f docker-compose.prebuilt.yml logs --tail=200 migrate
```

Updater logs are written to:

```text
/var/log/otclick-hh/update-*.log
```

### Restart an application service

```bash
cd /opt/otclick-hh
docker compose -f docker-compose.yml -f docker-compose.prebuilt.yml restart api worker frontend
```

### Health check

```bash
curl -fsS http://127.0.0.1:8000/health
```

### Important production rule

Do not use this as an update command:

```bash
docker compose up -d --build
```

That is a development/local-build path and bypasses the prebuilt artifact contract.

---

## Development

Local development is allowed to build from source. Production is not.

### Backend

```bash
git clone https://github.com/gest0r1/Otclick-hh.git
cd Otclick-hh
uv sync --dev
python3 infra/bootstrap.py --openai-key ""
docker compose up -d db migrate auth rest realtime storage kong
cd backend
uv run uvicorn app.main:app --reload
```

Checks:

```bash
uv run ruff check backend
cd backend && uv run pytest tests -q
```

### Frontend

```bash
cd frontend
npm ci
cp .env.local.example .env.local
npm run dev
```

Checks:

```bash
npx tsc --noEmit
npm test
```

### Firefox extension

```bash
cd ext
npm ci
npx tsc --noEmit
npm test
npm run build
```

---

## CI / artifact pipeline

`.github/workflows/ci.yml` validates backend, frontend and extension tests, including the incremental-installer regression contract.

`.github/workflows/build-artifact.yml` is the production image pipeline. For every pushed commit on `main` (and deployment test branches) it:

1. validates installer syntax and the merged production Compose configuration;
2. computes content hashes for backend, frontend, Compose, infra and migrations;
3. reuses an existing immutable GHCR component when its content hash did not change;
4. otherwise builds and publishes only the changed component;
5. smoke-tests frontend runtime `NEXT_PUBLIC_*` injection;
6. logs out of GHCR and verifies both component images can be pulled **anonymously**, exactly as a production server does;
7. creates per-component Release fallbacks only once per content hash;
8. retains a combined `otclick-images-linux-amd64.tar.gz` only for fresh install compatibility;
9. publishes a schema-v2 exact-SHA `manifest.json` containing immutable image digests;
10. downloads the published metadata again and verifies its SHA and image references.

The installer accepts only the manifest whose `git_sha` exactly matches the target repository SHA.

---

## Project structure

```text
Otclick-hh/
├── install.sh                       # one-command entry; routes existing installs to incremental updater
├── install-update.sh                # hash-aware GHCR incremental production updater
├── docker-compose.yml               # base self-hosted stack
├── docker-compose.prebuilt.yml      # production prebuilt-image/runtime-env override
├── .env.example
├── .github/workflows/
│   ├── ci.yml
│   └── build-artifact.yml
├── backend/
├── frontend/
├── ext/
├── infra/
│   ├── bootstrap.py
│   ├── frontend-runtime-env.sh
│   └── supabase/
│       ├── migrate.sh
│       └── migrations/
├── docs/
├── pyproject.toml
└── uv.lock
```

---

## Security notes

- Never commit `.env`.
- Keep `FERNET_KEY` backed up offline.
- Never regenerate secrets automatically for an existing database.
- Production updates must come from the exact Git commit and its matching verified artifact.
- Never use `docker compose down -v` for a normal update.

---

## License and upstream

This repository is based on the open-source Otclick project and retains the existing [`LICENSE`](LICENSE). For this deployment, use `https://github.com/gest0r1/Otclick-hh` as the source of truth.
