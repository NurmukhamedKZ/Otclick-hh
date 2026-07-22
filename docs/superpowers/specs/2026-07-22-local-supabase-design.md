# Local self-hosted Supabase stack

## Problem

Otclick is pitched as self-hostable/privacy-first ("all data stays on your infrastructure"),
but the only working setup today requires a **cloud** Supabase project (DB + Auth + Storage +
Realtime). Self-hosters must sign up for a third-party managed service just to run the app
locally/on their own VPS. `infra/docker-compose.yml` (VPS prod compose) has already been
deleted in favor of a single root `docker-compose.yml`, which still assumes cloud Supabase.

## Goal

Ship a local, self-hosted Supabase stack as the **default** self-host path, with zero changes
to application code (backend or frontend) — because both already talk to Supabase purely
through `SUPABASE_URL` + `SUPABASE_ANON_KEY` + `SUPABASE_SERVICE_ROLE_KEY` env vars via the
standard `supabase-py` / `@supabase/ssr` client libraries. Cloud Supabase remains a fully
supported alternative — same env vars, just pointed at a `*.supabase.co` project instead.

## Non-goals

- No changes to RLS policies, JWT validation logic (`backend/app/api/deps.py`,
  `backend/app/db/supabase.py`), Realtime notification delivery, or Storage upload code paths.
- No custom auth/session implementation — GoTrue (Supabase's auth server) keeps issuing the
  JWTs the app already validates.
- Not migrating away from Postgres-flavored SQL/RLS/triggers already in
  `infra/supabase/migrations/`.

## Design

### 1. Compose services

Add the self-hosted Supabase services (per the official `supabase/docker` reference compose)
to the root `docker-compose.yml`, alongside existing `api` / `worker` / `frontend`:

- `db` — Postgres (Supabase's image, includes `auth`/`storage`/`realtime` schemas + extensions)
- `auth` — GoTrue
- `rest` — PostgREST (used internally by supabase-py's non-DB-direct calls, and by PostgREST-
  dependent Supabase features)
- `realtime` — Supabase Realtime server
- `storage` — Storage API (serves the `captcha-screenshots` bucket)
- `kong` — API gateway, single entrypoint (`SUPABASE_URL` = `http://kong:8000` internally,
  `http://localhost:8000` from the host)

`api` and `worker` depend on `kong` being healthy the same way they currently depend on the
Supabase cloud URL being reachable — no code change, just `SUPABASE_URL` pointed locally.

### 2. Migrations — auto-run on first boot

Mount `infra/supabase/migrations/*.sql` into the `db` container's
`/docker-entrypoint-initdb.d/`, numbered/prefixed to run **after** Supabase's own init SQL
(which creates the `auth`/`storage`/`realtime` schemas, roles, and extensions) so the app
migrations' `auth.users` foreign keys and RLS policies resolve correctly. Postgres runs every
`.sql` file in `/docker-entrypoint-initdb.d/` in filename order, once, only on first volume
init — `docker compose up` alone yields a fully migrated DB.

The `captcha-screenshots` Storage bucket is created the same way (a small init SQL inserting
into `storage.buckets`, or a one-line init script), so it exists before the app ever tries to
upload to it.

### 3. Keys

Self-hosted Supabase needs a `JWT_SECRET` and two tokens derived from it (`ANON_KEY`,
`SERVICE_ROLE_KEY`, HS256 — simpler than cloud's ES256, and both GoTrue/PostgREST/backend
support HS256 fine since validation goes through the Supabase client, not manual JWT parsing).
`backend/.env.example` / `frontend/.env.local.example` document how self-hosters generate
these (a short generation script or documented steps) — no Supabase account needed to get a
working local stack.

### 4. Google OAuth — optional, off by default

`auth/page.tsx` has a "continue with Google" button requiring a Google Cloud Console OAuth
client configured in GoTrue. The local stack ships with the Google provider **disabled** by
default (no `GOOGLE_CLIENT_ID`/`SECRET` needed to get started). Frontend checks an env flag
(e.g. `NEXT_PUBLIC_GOOGLE_AUTH_ENABLED`) to hide the button when the provider isn't
configured, so self-hosters don't hit a dead button. README documents the opt-in steps
(create a Google Cloud Console OAuth client, set the two env vars, flip the flag) for anyone
who wants Google login.

### 5. Cloud Supabase stays supported

Because everything is env-var driven, `README.md` documents both paths side by side:

- **Local (default):** `docker compose up -d --build` — spins up the full self-hosted stack.
- **Cloud (alternative):** point `SUPABASE_URL`/keys at a managed Supabase project, skip the
  local `db`/`auth`/`rest`/`realtime`/`storage`/`kong` services (e.g. via a compose profile or
  a documented "comment these services out" step).

## Testing / verification

- Fresh `docker compose up -d --build` on a clean checkout → migrations applied, `/health`
  green, sign-up/login round-trip (email/password) works end-to-end through the UI.
- Captcha screenshot upload/read round-trips through local Storage.
- A worker-triggered notification insert shows up in the dashboard via local Realtime.
- Existing `backend/tests/` suite still passes unmodified (it mocks Supabase client calls, so
  it's insulated from this change).
- Manually verify pointing env vars at a cloud Supabase project still works (no code path
  regression for that option).
