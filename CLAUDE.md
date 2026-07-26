# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Otclick** (public repo: `NurmukhamedKZ/Otclick`, MIT license) — open-source AI agent for hh.ru/hh.kz job application automation. Self-hostable, privacy-first. See `README.md` for the public-facing pitch, feature list, and roadmap. Sub-projects:

- **`backend/`** — FastAPI service (active build) + standalone worker (`worker_main.py`)
- **`frontend/`** — Next.js 16 + React 19 + Tailwind v4 (Supabase SSR auth)
- **`hh-applicant-tool/`** — existing Python CLI tool (source to copy from, not modify)
- **`MVP_PLAN.md`** — day-by-day build plan; check before starting work

Open-source implications for this file:
- README.md is now the canonical **public** entrypoint (setup, features, roadmap, contributing) — keep this CLAUDE.md focused on internal architecture/dev guidance, don't duplicate README content, update both when a change affects both audiences.
- Contributions come from external contributors via PR — surface conventions here (Simplicity First, Surgical Changes, etc.) apply doubly since reviewers may not have full context.
- Never commit secrets/`.env` values — repo is public. `backend/.env.example` and `frontend/.env.local.example` are the templates contributors copy.
- `docker-compose.yml` (repo root) is the single-command self-host path (backend + worker + frontend) referenced in README Quick Start.

Key discovery: hh.ru password grant OAuth is **broken** (`unsupported_grant_type`). Playwright headless browser is the only working login method.

## Commands

Deps managed by `uv` (root `pyproject.toml` + `uv.lock`, Python ≥3.13). Run with `.venv` active or prefix with `uv run`:

```bash
source .venv/bin/activate   # or: uv sync && source .venv/bin/activate

# Dev server
cd backend && uvicorn app.main:app --reload

# Standalone worker (systemd entrypoint)
cd backend && python worker_main.py

# Frontend dev
cd frontend && npm run dev

# All tests (tests/integration/ + tests/e2e/ auto-skip unless the local stack is up)
cd backend && python -m pytest tests/ -v

# Local-stack smoke tests only — needs `docker compose up -d` + root .env
cd backend && python -m pytest tests/integration -v

# Browser e2e (Chromium → frontend → Kong → API) — also needs the frontend on :3000
cd backend && python -m pytest tests/e2e -v

# Single test
cd backend && python -m pytest tests/test_hh_auth.py::test_encrypt_decrypt_roundtrip -v

# Install playwright browsers (needed for OAuth flow)
playwright install chromium

# ─── Local Supabase stack (the ONLY environment — see below) ───
python3 infra/supabase/gen-keys.py     # once: JWT/API keys for root .env
docker compose up -d                   # db, auth, kong, storage, realtime, api, worker, frontend
docker compose ps                      # kong + db must be (healthy)

# Apply a NEW migration to an already-initialized volume (fresh volumes auto-run
# every migration via infra/supabase/init/zz2-run-app-migrations.sh)
docker exec -i aiautoclicker-db psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  < infra/supabase/migrations/023_analytics.sql

# psql shell / ad-hoc query
docker exec -it aiautoclicker-db psql -U postgres -d postgres

# api and worker run BAKED code — after backend edits the container needs a rebuild
docker compose build api && docker compose up -d api
```

## Supabase: local self-hosted only

There is **no hosted Supabase project** anymore — the stack in `docker-compose.yml` (Postgres + Auth + Kong + Storage + Realtime) is the single environment for dev and for self-hosters. Consequences:

- **Migrations run automatically only on a fresh volume**: `infra/supabase/init/zz2-run-app-migrations.sh` (a `docker-entrypoint-initdb.d` hook) replays every `infra/supabase/migrations/*.sql` in order the first time the `db` volume is created. On an **existing** volume that hook never fires again — a new migration must be applied by hand with `psql` (see Commands), then verified (`\d applications`, or select from the new object). No `supabase db push`, no MCP `apply_migration`: those talk to hosted projects and are useless here.
- **Two URLs, on purpose**: `SUPABASE_URL=http://kong:8000` is in-network (backend/worker containers). `SUPABASE_PUBLIC_URL` / `NEXT_PUBLIC_SUPABASE_URL=http://localhost:54321` is browser-side. Swapping them breaks whichever side got the wrong one, and the failure looks like a network error, not a config error.
- **Keys come from `infra/supabase/gen-keys.py`**, not from a dashboard: one `JWT_SECRET` + HS256 anon/service tokens signed with it (10-year exp, rotate by re-running the script). All three must move together — `ANON_KEY`/`SERVICE_ROLE_KEY` (stack-level, consumed by auth/rest/kong) have to equal `SUPABASE_ANON_KEY`/`SUPABASE_SERVICE_ROLE_KEY` (app-level), and any of them signed by a different secret gives blanket 401s.
- `NEXT_PUBLIC_API_URL=http://localhost:8000` is the FastAPI backend, **not** Kong on 54321. Next bakes it at build time.
- Full setup walkthrough lives in README Quick Start (it's the public-facing self-host guide); don't duplicate it here.

## Required `.env` (backend root or project root)

```
SUPABASE_URL=http://kong:8000            # in-network; localhost:54321 from the host
SUPABASE_PUBLIC_URL=http://localhost:54321
SUPABASE_ANON_KEY=                       # from infra/supabase/gen-keys.py
SUPABASE_SERVICE_ROLE_KEY=               # from infra/supabase/gen-keys.py
FERNET_KEY=   # generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# AI (cover letters, form-test answers, recruiter chat). Empty key → fallback templates.
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5.4-nano

# hh refresh-token cron (shared secret for /internal/cron/*)
INTERNAL_CRON_TOKEN=

# CloudPayments billing
CLOUDPAYMENTS_PUBLIC_ID=
CLOUDPAYMENTS_API_SECRET=   # HMAC key for webhook verification — never exposed
```

All non-secret config (rate limits, plan price, prompts, `REFRESH_THRESHOLD_DAYS`) has defaults in `config.py`.

## Backend Architecture (`backend/app/`)

```
main.py                      — FastAPI app, /health checks Supabase
config.py                    — pydantic-settings Settings (reads .env), Fernet lazy init
api/
  deps.py                    — get_current_user: validates Supabase JWT via anon_client
  auth.py                    — /api/hh/* (connect, poll, captcha, disconnect, status)
  resumes.py                 — /api/resumes/* (sync, list)
  filters.py                 — /api/filters/* (CRUD + vacancy preview)
  blacklist.py               — /api/blacklist/* (employer blacklist CRUD)
  captcha.py                 — /api/captcha/* (pending list, solve, dismiss)
  worker.py                  — /api/worker/* (status/control per user; plan-gated start)
  forms.py                   — /api/forms/drafts (list, approve→post to hh, discard)
  chats.py                   — /api/chats (list negotiations, get messages, send message)
  recruiter.py               — /api/recruiter (escalation drafts send/discard, todos done/dismiss)
  analytics.py               — /api/analytics?days= (syncs hh negotiation states, then one RPC)
  billing.py                 — /api/billing/* (subscribe params, status, cancel)
  webhooks.py                — /api/webhooks/cloudpayments (HMAC-auth, no JWT)
  internal.py                — /internal/cron/* (X-Internal-Token, no JWT) → token refresh
  _debug.py                  — debug-only routes, mounted iff DEBUG_ENDPOINTS
  router.py                  — aggregates all routers
ai/
  agent.py                   — HHAgent: one ChatOpenAI shared by every AI path (write_form_answers, write_cover_letter, answer_recruiter, answer_recruiter_choice, filter_relevant_vacancies) — see below
  prompts.py                 — system prompts + builders; sanitize_ai_text (strip md/em-dashes)
  recruiter_tools.py         — langchain @tool defs for recruiter agent (send / escalate / make_todo)
worker/
  runner.py                  — per-user apply loop + WorkerRegistry; captcha pause/poll; recruiter poll + heartbeat
  recruiter_poll.py          — poll_recruiter_chats: once per loop iter, run agent on new employer messages
  queue.py                   — in-memory per-user ApplyJob queue
  limiter.py                 — daily/hourly apply caps (apply_counters table, per-user tz)
  throttle.py                — inter-request delay + SessionCluster human-like breaks
db/
  supabase.py                — service_client (bypasses RLS), anon_client (JWT validation only)
hh/
  authorize.py               — Playwright OAuth flow → auth code + captured web cookies
  client.py                  — ApiClient + OAuthClient (thread-safe, rate-limited, auto refresh)
  client_keys.py             — ANDROID_CLIENT_ID/SECRET (hardcoded, from hh-applicant-tool)
  errors.py                  — ApiError hierarchy (Forbidden, CaptchaRequired, LimitExceeded, …)
  datatypes.py               — hh API payload typed dicts
  user_agent.py              — random Android UA generator
services/
  hh_auth.py                 — async OAuth job manager + Fernet encrypt/decrypt + persist
  hh_credentials.py          — load ApiClient from stored creds; persist if auto-refreshed
  token_refresh.py           — refresh_user (one) + refresh_due (near-expiry cron batch)
  resume_sync.py             — pull /resumes/mine → upsert resumes table
  filters_service.py         — filters CRUD + vacancy preview with excluded_regex
  vacancy_producer.py        — search per enabled filter → dedup/blacklist/exclude → AI relevance filter (if filter.ai_filter_enabled) → queue
  apply.py                   — apply_one: one /negotiations submit; maps hh errors → ApplyStatus
  form_filler.py             — solve vacancy tests over hh.ru web session (no browser); returns answers, no submit
  form_drafts.py             — form-draft persistence + approval; approve() re-fetches xsrf, posts to hh
  cover_letter.py            — cover letter gen with PG cache + rand_text fallback
  blacklist.py               — employer blacklist CRUD + bulk auto-blacklist
  billing.py                 — CloudPayments HMAC verify, idempotent payment, plan activate
  plan.py                    — has_access / check_access + filter_accessible (drops users w/o plan)
  captcha.py                 — captcha_requests create/solve/dismiss helpers
  recruiter.py               — recruiter-chat persistence + new_employer_message cursor; shared by tools/poller/API
  chatik.py                  — chatik.hh.ru web API client (recent_chats/chat_messages/fetch_messages); real source of truth for chats — legacy negotiations API is frozen. Reads over stored web session (same cookies as form_filler), no browser
  negotiation_sync.py        — mirror hh negotiation state (response|invitation|discard) + viewed flag into applications; on-demand, throttled by profiles.negotiations_synced_at
  analytics.py               — funnel metrics via the analytics_summary PG function (fail-soft: rpc error → empty shape)
  relevance.py               — batch semantic relevance filter (filter_relevant) + relevance_cache helpers; conservative + fail-open (any failure → keep all)
  worker_control.py          — persisted on/off intent (profiles.worker_enabled); enabled_active_user_ids
  worker_runtime.py          — runner heartbeat → worker_runtime table so API /api/worker/status can read it
  notifications.py           — insert notifications rows (UI reads via Realtime)
schemas/
  auth.py, resumes.py, filters.py, blacklist.py, billing.py, recruiter.py — Pydantic models
```

## Key Design Patterns

**OAuth job flow**: `POST /api/hh/connect` → creates async job (UUID) → returns immediately → client polls `GET /api/hh/connect/{job_id}`. Job runs Playwright in background task (`asyncio.create_task`).

**Captcha handoff (plan-A, OAuth path)**: when Playwright sees captcha, job pauses at `captcha_queue.wait_for()` (5-min timeout), uploads screenshot to Supabase Storage, client sees `captcha_required` + signed URL → user solves → `POST /api/hh/connect/{job_id}/captcha`.

**Captcha handoff (plan-B, worker path)**: worker hitting captcha during apply inserts a `captcha_requests` row → user lists via `/api/captcha/pending`, solves via `/api/captcha/{id}/solve` (or dismisses) → runner polls queue and resumes.

**Worker model**: decoupled from "connected" via `profiles.worker_enabled`. Dashboard Start/Stop flips the flag (`worker_control.set_enabled`); the worker no longer auto-applies for every connected user at boot. `worker_main.py` polls `worker_control.enabled_active_user_ids` every `POLL_INTERVAL_S` → `plan.filter_accessible` drops users without a valid plan → reconciles runners (start enabled, stop disabled) via `get_registry()` (`WorkerRegistry` in `runner.py`). Each runner loop: refill queue via `vacancy_producer.produce_jobs` → check `limiter` caps → `throttle` sleep → `apply.apply_one` → handle `ApplyStatus` → `poll_recruiter_chats`. Runner writes `worker_runtime.heartbeat` (state/queued/today_count/next_run_at/last_error) so the API process — which lacks the in-memory queue — can serve `/api/worker/status`. Captcha pauses the runner and polls `GET /me` until cleared. Graceful shutdown on SIGTERM/SIGINT.

**Apply pipeline** (`apply.apply_one`): resolve resume → skip if already applied → fetch vacancy once (drives 3 decisions: `has_test`, `employer_id`, `response_letter_required`). `has_test` → AI fills answers but the worker **NEVER auto-submits** — drops a `form_draft` (status `pending`) for user approval and records `form_required`; the `form_required` pre-record is not a real attempt, so it allows re-evaluation later. Letter required → generate cover letter (else empty message). `POST /negotiations`, then map every hh error to an `ApplyStatus` literal (`sent`/`form_sent`/`captcha`/`token_dead`/`account_banned`/`form_required`/`resume_missing`/`vacancy_gone`/…). Producer also pre-records `has_test` vacancies as `form_required` so they surface in the UI without burning an apply attempt, and auto-blacklists employers on "already applied" / non-empty `relations`.

**Form-draft approval**: `form_drafts.py` — AI-filled test answers land as a `form_drafts` row (`pending`). User reviews in the UI; `/api/forms/drafts/{id}/approve` re-fetches xsrf and POSTs to hh (`approve()`), `/discard` dismisses. `form_filler` returns answers only — submission moved here.

**Recruiter chat agent**: each runner loop calls `poll_recruiter_chats` (`worker/recruiter_poll.py`) → `chatik.recent_chats` (NOT legacy negotiations API — it's frozen and misses bot questions, our replies, and real-recruiter messages after the robot leaves) → `recruiter.new_employer_message` (cursor on `last_handled_id`, NOT `viewed_by_me`, to avoid double-replies) → `HHAgent.answer_recruiter` or, when the chatik message carries quick-reply buttons (`actions.text_buttons`), `answer_recruiter_choice` (same agent/tools/memory, but the reply MUST exactly match a button label or hh loops). Tools (`recruiter_tools.py`): `send_message_recruiter` (reply on hh — POSTed via legacy messages API, still lands in chatik), `escalate_to_human` (write `recruiter_drafts` row for user approval via `/api/recruiter/drafts`), `make_todo` (`recruiter_todos`). Errors are logged and never crash the runner loop. `/api/chats` reads messages from chatik (falls back to stale legacy API when no web session); manual send via `/api/chats/{id}/messages`.

**Centralized AI (`HHAgent`)**: one `HHAgent` per runner (`ai/agent.py`) wraps a single rate-limited `ChatOpenAI`. ALL LLM work routes through it — `write_form_answers` (form_filler), `write_cover_letter` (cover_letter), `answer_recruiter` / `answer_recruiter_choice` (langchain agent w/ per-chat memory + `recruiter_tools.py` tools), `filter_relevant_vacancies` (relevance, grounded in the filter's resume summary). No per-call LLM construction. Empty `OPENAI_API_KEY` → helpers fall back to templates/heuristics, never crash. All AI text passes `prompts.sanitize_ai_text` (strips markdown bold/emphasis + em-dashes).

**Form-test solving (`form_filler.py`)**: hh vacancy tests are solved over the **hh.ru web session** (not the API) using cookies captured during OAuth login (`web_cookies_encrypted`, Fernet). Parses `vacancyTests` + `xsrfToken` out of the page's inline JSON, answers each task via the shared LLM grounded in a resume summary. No browser, no re-login. **Does not submit** — returns answers; the actual POST to `vacancy_response/popup` happens in `form_drafts.approve()` after user approval. Failure → `form_required` fallback.

**Cover letter cache**: `cover_letter.generate` keys on `(vacancy_id, resume_id)` in `cover_letters_cache` (PG). Hit → skip OpenAI. Miss → LLM → on failure, `rand_text` `{a|b}` template. All writes service_role.

**Analytics funnel**: `GET /api/analytics?days=` → `negotiation_sync.sync_states` (paged `GET /negotiations`, `order_by=updated_at`, writes only actual state changes so `hh_state_at` really means "when it changed"; throttled to 5 min per user, never raises) → `analytics.summary` → `analytics_summary()` in PG. Funnel: AI-checked → AI-kept → sent → viewed (`hh_viewed`) → replied (`hh_state` moved OR a `recruiter_chats` row saw an employer message) → invited (`hh_state='invitation'`). "Sent" counts only `sent`/`form_sent` rows — `form_required`/`failed`/`captcha` never reached hh and land in the failures breakdown instead. Rates are `null` when the denominator is 0; the UI prints "—", never a fake 0%. Attribution comes from `applications.filter_id` (passed `producer → ApplyJob → apply_one`) and `employer_name`, both set on new rows only — historical rows show up as "без фильтра".

**Plan gating**: `plan.has_access` — `trial` until `trial_ends`, `active`/`cancelled` until `plan_expires_at`, else no access. Gates worker start (`/api/worker`) and `worker_main`.

**Billing**: CloudPayments widget (params from `billing.subscribe_params`) → card charge → server-to-server POST to `/api/webhooks/cloudpayments`. Webhook verifies `Content-HMAC` (HMAC-SHA256 over raw body), records payment idempotently (`TransactionId` → `payments.provider_payment_id` UNIQUE), activates plan only on a genuinely new row. Always answers CP `{"code": 0}` once HMAC valid so it stops retrying.

**Token refresh cron**: `POST /internal/cron/refresh-tokens` (guarded by `X-Internal-Token`) → `token_refresh.refresh_due` refreshes only creds expiring within `REFRESH_THRESHOLD_DAYS` (hh refresh tokens are single-use, only usable after the access token expires). Trigger from system cron.

**Notifications**: worker events (`apply_success`, `captcha`, `limit_reached`, `token_dead`, `account_banned`, …) insert `notifications` rows; the frontend reads them via Supabase Realtime.

**Supabase client split**: `anon_client` only for JWT validation. `service_client` for all DB/storage writes (bypasses RLS). All sync Supabase calls run in `loop.run_in_executor` — never block the event loop.

**Token credential flow**: `hh_credentials.load_api_client` decrypts tokens → builds `ApiClient` → caller saves `original_access = client.access_token` before calling hh API → after the call, `persist_if_refreshed` re-encrypts and saves if `ApiClient` auto-refreshed the token.

**Token encryption**: Fernet symmetric encryption for hh tokens in `hh_credentials` table. `service_role` key only — no user-visible access.

**hh API client**: `BaseClient` → `OAuthClient` (token exchange) + `ApiClient` (API calls with auto token refresh on 403). Thread-safe via `Lock`. Rate-limited, default 0.345s delay.

## Frontend (`frontend/src/`)

Next.js App Router. Authed pages under `app/(app)/` (dashboard, applications, analytics, billing, account, notifications, chats, todo) behind `(app)/layout.tsx`; public `auth/`, `onboarding/`, landing `page.tsx`. Supabase SSR auth split across `lib/supabase/{client,server,middleware}.ts`.

- `lib/api.ts` — `apiFetch`: attaches the Supabase session JWT as `Bearer` to every backend call (backend `deps.get_current_user` validates it). Base URL from `NEXT_PUBLIC_API_URL`.
- `hooks/` — `useHHConnect`, `useFilters`, `useBlacklist` wrap the backend endpoints.
- `components/otclick/` — app chrome (sidebar, topbar, worker-bar, hh-banner); top-level `captcha-modal`, `filters-drawer`, `toaster`.
- Notifications stream in via Supabase Realtime (matches backend `notifications` inserts).

Env: `frontend/.env.local` (see `.env.local.example`) — `NEXT_PUBLIC_API_URL=http://localhost:8000` (the backend, not Kong), `NEXT_PUBLIC_SUPABASE_URL=http://localhost:54321`, anon key from `gen-keys.py`. The dockerized frontend bakes these at build time (`docker compose build frontend` after changing them).

## Supabase Tables

Migrations live in `infra/supabase/migrations/` (numbered SQL files, `001`–`023`). Applied by hand via `psql` into the local stack — see Commands.

- `profiles` — user profiles + plan state (`plan`, `trial_ends`, `plan_expires_at`, `cp_subscription_id`, `worker_enabled`)
- `hh_credentials` — encrypted hh tokens + `web_cookies_encrypted` per user (full RLS denial, service_role only)
- `resumes` — user resume list synced from hh, unique on `(user_id, hh_resume_id)`
- `filters` — saved vacancy search filters per user
- `applications` — apply attempts/results, unique on `(user_id, vacancy_id)`; stores status, cover_letter, `form_answers`
- `blacklist` — blacklisted employers per user, unique on `(user_id, employer_id)`
- `apply_counters` — per-user daily/hourly apply tallies (limiter)
- `cover_letters_cache` — generated cover letters keyed on `(vacancy_id, resume_id)`
- `vacancy_cache` — cached hh vacancy payloads
- `payments` — CloudPayments transactions, unique on `provider_payment_id`
- `notifications` — worker→UI events (read via Realtime)
- `captcha_requests` — pending captcha challenges raised by worker
- `form_drafts` — AI-filled test answers awaiting user approval (service_role only)
- `recruiter_chats` — per-negotiation agent state/cursor (`last_handled_id`)
- `recruiter_drafts` — agent escalations awaiting human send (incl. `question_text`)
- `recruiter_todos` — agent-created todos for the user
- `worker_runtime` — runner heartbeat (state/queued/today_count/next_run_at/last_error), read by API
- `relevance_cache` — AI vacancy relevance verdicts, unique on `(resume_id, vacancy_id)`; service_role only. Migration 015 also adds `filters.ai_filter_enabled`
- `qa_memory` — user-curated Q&A (only answers the user EDITED when approving a form draft, plus manual entries), unique on `(user_id, question)`; service_role only. `services/qa_memory.prompt_block` injects it into form-test and recruiter prompts (migration 022)
- `captcha-screenshots` — Supabase Storage bucket for captcha images

Migration 023 adds analytics: `applications.hh_state`/`hh_state_at`/`hh_viewed` (mirrored negotiation state — the only honest source for "invited to interview"), `applications.filter_id`/`employer_name` (breakdown attribution), `profiles.negotiations_synced_at`, and the `analytics_summary(user_id, days)` PG function that returns every metric as one jsonb (service_role only; revoked from anon/authenticated).

Migrations 010–015 add the recruiter tables, `worker_enabled`, `form_drafts`, recruiter `question_text`, `worker_runtime`, and the relevance cache + `filters.ai_filter_enabled`.

## Tests

Tests set env vars before importing app modules (avoids pydantic-settings crash):

```python
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
# ... other required vars
# THEN import from app.*
```

Tests are unit-level (no real Supabase/Playwright). Async tests use `pytest-asyncio`. Supabase chain calls are mocked with a fluent `MagicMock` helper (see `test_filters_service.py::_fluent`).

## What to Reuse from `hh-applicant-tool/`

Already ported: `client.py`, `client_keys.py`, `authorize.py` (selectors updated — old ones stale), apply/filter pipeline (`services/apply.py`, `vacancy_producer.py`), AI (`ai/agent.py` + LLM-backed services), `rand_text` (`services/cover_letter.py`).

The CLI tool remains a reference for hh API quirks — read it, don't modify it.

----

1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:

    State your assumptions explicitly. If uncertain, ask.
    If multiple interpretations exist, present them - don't pick silently.
    If a simpler approach exists, say so. Push back when warranted.
    If something is unclear, stop. Name what's confusing. Ask.

2. Simplicity First

Minimum code that solves the problem. Nothing speculative.

    No features beyond what was asked.
    No abstractions for single-use code.
    No "flexibility" or "configurability" that wasn't requested.
    No error handling for impossible scenarios.
    If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.
3. Surgical Changes

Touch only what you must. Clean up only your own mess.

When editing existing code:

    Don't "improve" adjacent code, comments, or formatting.
    Don't refactor things that aren't broken.
    Match existing style, even if you'd do it differently.
    If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

    Remove imports/variables/functions that YOUR changes made unused.
    Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.
4. Goal-Driven Execution

Define success criteria. Loop until verified.

Transform tasks into verifiable goals:

    "Add validation" → "Write tests for invalid inputs, then make them pass"
    "Fix the bug" → "Write a test that reproduces it, then make it pass"
    "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.