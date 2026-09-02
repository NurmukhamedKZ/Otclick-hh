# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Otclick** (public repo: **https://github.com/NurmukhamedKZ/Otclick-hh**, MIT license — this is the canonical URL for clones, badges and README links; the older `NurmukhamedKZ/Otclick` name is stale) — open-source AI agent for hh.ru/hh.kz job application automation. Self-hostable, privacy-first. See `README.md` for the public-facing pitch, feature list, and roadmap. Sub-projects:

- **`backend/`** — FastAPI service (active build) + standalone worker (`worker_main.py`)
- **`frontend/`** — Next.js 16 + React 19 + Tailwind v4 (Supabase SSR auth)
- **`hh-applicant-tool/`** — existing Python CLI tool (source to copy from, not modify)
- **`ext/`** — Firefox extension (WXT, MV2): autofills Google/Yandex/MS Forms + an AI chat tab, served by `/api/extension/*`. Forked from `extension/` (a gitignored copy of the OtclickUS extension kept as a porting source — never edit that copy). See `ext/README.md`
- **`AUDIT.md`** — production-readiness audit: what's fixed, what's still open (older items; the CloudPayments amount-check and manual-cancel entries are obsolete — billing is Polar now). Read it before shipping anything near billing or the worker.

Open-source implications for this file:
- README.md is now the canonical **public** entrypoint (setup, features, roadmap, contributing) — keep this CLAUDE.md focused on internal architecture/dev guidance, don't duplicate README content, update both when a change affects both audiences.
- Contributions come from external contributors via PR — surface conventions here (Simplicity First, Surgical Changes, etc.) apply doubly since reviewers may not have full context.
- Never commit secrets/`.env` values — repo is public. `.env.example` (repo root, the single env file) and `frontend/.env.local.example` are the templates contributors copy.
- `docker-compose.yml` (repo root) is the single-command self-host path (backend + worker + frontend) referenced in README Quick Start.
- CI lives in `.github/workflows/ci.yml`: ruff + pytest for the backend, `tsc --noEmit` + `npm test` for the frontend and for `ext/` (plus a Firefox build), on every PR.

Key discovery: hh.ru password grant OAuth is **broken** (`unsupported_grant_type`). Playwright headless browser is the only working login method. Two Playwright flows: password (`authorize.get_auth_code`) and passwordless email-code (`authorize.get_auth_code_via_email_code`).

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
python3 infra/bootstrap.py             # once: writes the root .env, all secrets generated
docker compose up -d                   # db, migrate, auth, kong, storage, realtime, api, worker, frontend
docker compose ps                      # kong + db must be (healthy)

# Migrations are applied by the one-shot `migrate` service on every `up`
# (infra/supabase/migrate.sh, ledger = public.schema_migrations). To run it alone:
docker compose up migrate
docker compose logs migrate

# psql shell / ad-hoc query
docker exec -it aiautoclicker-db psql -U postgres -d postgres

# api and worker run BAKED code — after backend edits the container needs a rebuild
docker compose build api && docker compose up -d api
```

## Supabase: local self-hosted only

There is **no hosted Supabase project** anymore — the stack in `docker-compose.yml` (Postgres + Auth + Kong + Storage + Realtime) is the single environment for dev and for self-hosters. Consequences:

- **Migrations run through one idempotent script**, `infra/supabase/migrate.sh`: it applies every `infra/supabase/migrations/*.sql` not yet recorded in `public.schema_migrations`, each in its own transaction. It runs from two places — the `docker-entrypoint-initdb.d` hook (`init/zz2-run-app-migrations.sh`, fresh volume only) and the one-shot `migrate` compose service that `api` depends on (`service_completed_successfully`). So on an existing volume a new migration lands on the next `docker compose up`; nothing is ever replayed. A pre-ledger database is **baselined** on first run (every file on disk recorded as applied, nothing executed) — if you upgraded code and DB in one step, verify the newest migrations really landed. No `supabase db push`, no MCP `apply_migration`: those talk to hosted projects and are useless here.
- **Two URLs, on purpose**: `SUPABASE_URL=http://kong:8000` is in-network (backend/worker containers). `SUPABASE_PUBLIC_URL` / `NEXT_PUBLIC_SUPABASE_URL=http://localhost:54321` is browser-side. Swapping them breaks whichever side got the wrong one, and the failure looks like a network error, not a config error.
- **Keys come from `infra/bootstrap.py`** (which fills the whole `.env`; `infra/supabase/gen-keys.py` prints just the triple), not from a dashboard: one `JWT_SECRET` + HS256 anon/service tokens signed with it (10-year exp, rotate by re-running the script). All three must move together — `ANON_KEY`/`SERVICE_ROLE_KEY` (stack-level, consumed by auth/rest/kong) have to equal `SUPABASE_ANON_KEY`/`SUPABASE_SERVICE_ROLE_KEY` (app-level), and any of them signed by a different secret gives blanket 401s.
- `NEXT_PUBLIC_API_URL=http://localhost:8000` is the FastAPI backend, **not** Kong on 54321. Next bakes it at build time.
- Full setup walkthrough lives in README Quick Start (it's the public-facing self-host guide); don't duplicate it here.

## Required `.env` (repo root — the ONLY env file)

`cp .env.example .env` at the repo root. One file feeds all three consumers: compose's own
`${...}` substitutions (stack keys, frontend build args), the `api`/`worker` containers
(`env_file: .env`), and `cd backend && uvicorn` (`config.py` reads `("../.env", ".env")`).
There is no `backend/.env.example` anymore.

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

# hh OAuth app. Empty → the official Android app's borrowed keys, which answer
# `error=geo_forbidden` on /oauth/authorize outside their region (login succeeds,
# hh then refuses the code). Fix: your own app on dev.hh.ru/admin or dev.hh.kz/admin.
# All three move together; HH_REDIRECT_URI must match the registration byte for byte.
HH_CLIENT_ID=
HH_CLIENT_SECRET=
HH_REDIRECT_URI=

# cron endpoints (shared secret for /internal/cron/*: refresh-tokens, prune-notifications)
INTERNAL_CRON_TOKEN=

# Polar.sh billing (merchant of record). Prices/intervals live in Polar products.
POLAR_ACCESS_TOKEN=
POLAR_WEBHOOK_SECRET=       # Standard Webhooks secret — never exposed
POLAR_SERVER=sandbox        # sandbox | production
POLAR_PRODUCT_SPRINT=       # product ids differ per Polar organisation
POLAR_PRODUCT_MONTH=
```

All non-secret config (rate limits, plan price, prompts, `REFRESH_THRESHOLD_DAYS`) has defaults in `config.py`.

## Backend Architecture (`backend/app/`)

```
main.py                      — FastAPI app; /health 503s on a dead DB (docker healthcheck depends on it)
config.py                    — pydantic-settings Settings (reads ../.env then .env), Fernet lazy init
api/
  deps.py                    — get_current_user: validates Supabase JWT via anon_client (60s result cache); require_active_plan
  auth.py                    — /api/hh/* (connect, poll, captcha, email code, refresh, disconnect, status)
  resumes.py                 — /api/resumes/* (sync, list)
  filters.py                 — /api/filters/* (CRUD + vacancy preview)
  blacklist.py               — /api/blacklist/* (employer blacklist CRUD)
  captcha.py                 — /api/captcha/* (pending list, solve, dismiss)
  worker.py                  — /api/worker/* (start/stop apply loop — free too, agent/start + agent/stop — paid, status)
  qa.py                      — /api/qa (list/upsert/delete user-curated Q&A memory)
  forms.py                   — /api/forms/drafts (list, approve→post to hh, discard)
  chats.py                   — /api/chats (list negotiations, get messages, send message)
  recruiter.py               — /api/recruiter (escalation drafts send/discard, todos done/dismiss)
  analytics.py               — /api/analytics?days= (syncs hh negotiation states, then one RPC)
  extension.py               — /api/extension/* (context, fill, chat, qa, resume-file) for the Firefox extension
  billing.py                 — /api/billing/* (subscribe→Polar checkout URL, portal, status)
  webhooks.py                — /api/webhooks/polar (Standard Webhooks signature, no JWT)
  internal.py                — /internal/cron/* (X-Internal-Token via hmac.compare_digest, no JWT) → refresh-tokens, prune-notifications
  _debug.py                  — debug-only routes, mounted iff DEBUG_ENDPOINTS
  router.py                  — aggregates all routers
ai/
  agent.py                   — HHAgent: one ChatOpenAI shared by every AI path (write_form_answers, write_cover_letter, answer_recruiter, answer_recruiter_choice, filter_relevant_vacancies) — see below
  prompts.py                 — system prompts + builders; sanitize_ai_text (strip md/em-dashes)
  recruiter_tools.py         — langchain @tool defs for the recruiter agent (answer_recruiter_question / escalate_to_human / make_todo) + match_label; every one of them writes a draft, none post to hh
worker/
  runner.py                  — per-user apply loop + independent recruiter loop + WorkerRegistry; captcha pause/poll; heartbeat
  recruiter_poll.py          — poll_recruiter_chats: run the agent on new employer messages; negotiation states cached 30 min per user
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
  filters_service.py         — filters CRUD + vacancy preview (excluded words go to hh as `excluded_text`)
  vacancy_producer.py        — search per enabled filter → round-robin + cross-filter dedup/blacklist → AI relevance filter (if filter.ai_filter_enabled) → queue
  apply.py                   — apply_one: one /negotiations submit; maps hh errors → ApplyStatus
  form_filler.py             — solve vacancy tests over hh.ru web session (no browser); returns answers, no submit
  form_drafts.py             — form-draft persistence + approval; approve() re-fetches xsrf, posts to hh
  cover_letter.py            — cover letter gen with PG cache + rand_text fallback
  blacklist.py               — employer blacklist CRUD + bulk auto-blacklist
  billing.py                 — Polar checkout/portal + webhook verify, idempotent order, plan state
  plan.py                    — limits_for/get_limits (free vs paid caps) + has_access/filter_paid (paid-only features)
  captcha.py                 — captcha_requests create/solve/dismiss helpers
  recruiter.py               — recruiter-chat persistence + new_employer_message cursor; shared by tools/poller/API
  chatik.py                  — chatik.hh.ru web API client (recent_chats/chat_messages/fetch_messages); real source of truth for chats — legacy negotiations API is frozen. Reads over stored web session (same cookies as form_filler), no browser
  negotiation_sync.py        — mirror hh negotiation state (response|invitation|discard) + viewed flag into applications; on-demand, throttled by profiles.negotiations_synced_at
  analytics.py               — funnel metrics via the analytics_summary PG function (rpc error → empty shape + `error: true`, so the UI shows "недоступна" instead of honest-looking zeroes)
  relevance.py               — batch semantic relevance filter (filter_relevant) + relevance_cache helpers; conservative + fail-open (any failure → keep all)
  worker_control.py          — persisted on/off intent (profiles.worker_enabled/agent_enabled); active_user_flags
  worker_runtime.py          — runner heartbeat → worker_runtime table so API /api/worker/status can read it
  notifications.py           — insert notifications rows (UI reads via Realtime)
  qa_memory.py               — user-curated Q&A store + prompt_block injected into form-test/recruiter prompts
  retention.py               — prune_notifications (called from /internal/cron/prune-notifications)
  candidate_context.py       — extension candidate context: load_resume + _resume_summary + qa_memory.prompt_block, plus the verbatim `facts` dict
  extension_resume.py        — hh resume PDF bytes for the extension's <input type=file>
schemas/
  auth.py, resumes.py, filters.py, blacklist.py, billing.py, recruiter.py — Pydantic models
```

## Key Design Patterns

**OAuth job flow**: `POST /api/hh/connect` → creates async job (UUID) → returns immediately → client polls `GET /api/hh/connect/{job_id}`. Job runs Playwright in a background task whose reference is kept on `JobState.task` (a bare `create_task` can be GC'd mid-flow). Passwordless variant: the same job pauses for the emailed code, submitted via `POST /api/hh/connect/{job_id}/code`. Admission control in `hh_auth._admit`: **one live job per user, `MAX_CONCURRENT_JOBS=4` globally** (429 otherwise) — each job is a headless Chromium. Finished jobs are purged after `FINISHED_JOB_TTL_S=600`. `_jobs` is process-local, so the API must run as a single process (or job state has to move to the DB).

**Captcha handoff (plan-A, OAuth path)**: when Playwright sees captcha, job pauses at `captcha_queue.wait_for()` (5-min timeout), uploads screenshot to Supabase Storage, client sees `captcha_required` + signed URL → user solves → `POST /api/hh/connect/{job_id}/captcha`.

**Captcha handoff (plan-B, worker path)**: worker hitting captcha during apply inserts a `captcha_requests` row → user lists via `/api/captcha/pending`, solves via `/api/captcha/{id}/solve` (or `/dismiss`, which only closes the modal — it no longer switches the worker off) → runner polls queue and resumes.

**Worker model**: two independent loops per user, both decoupled from "connected" — `profiles.worker_enabled` (auto-apply) and `profiles.agent_enabled` (recruiter agent). The dashboard flips them via `/api/worker/start|stop` and `/api/worker/agent/start|stop` (`worker_control.set_enabled` / `set_agent_enabled`); nothing auto-starts at boot. `worker_main.py` polls `worker_control.active_user_flags` every `POLL_INTERVAL_S=15` → `plan.filter_accessible` gates **both** flags → `registry.reconcile(uid, apply_on, agent_on)` starts/stops each loop separately (`WorkerRegistry` in `runner.py`). Apply loop: refill queue via `vacancy_producer.produce_jobs` → `limiter` caps → `throttle` sleep → `apply.apply_one` → handle `ApplyStatus`. Recruiter loop: `poll_recruiter_chats` every `RECRUITER_POLL_INTERVAL_S=120`, independent of apply limits. Empty producer runs back off exponentially (`IDLE_REFILL_SLEEP_S=10` → `IDLE_REFILL_MAX_SLEEP_S=15 min`, reset on a non-empty harvest) — retrying every 10s scans up to `MAX_PAGES_PER_FILTER` pages *per filter* and is the fastest way to get an account flagged. Runner writes `worker_runtime.heartbeat` (state/queued/today_count/next_run_at/last_error) so the API process — which lacks the in-memory queue — can serve `/api/worker/status`; heartbeats are published **before and after** every long sleep (cluster break, daily-limit sleep), else the UI shows "работает" for hours. Captcha pauses the loop and polls `GET /me` until cleared. A terminal stop (`token_dead` / `account_banned`) also clears `worker_enabled` (`runner._disable_worker`) — otherwise `worker_main` respawns the runner every 15 s and re-notifies forever. `/api/worker/status` reports **`starting`** while the flag is on but no live heartbeat exists yet (no row, or a stale `stopped` one), so the UI stops claiming "работает" before the runner exists. Graceful shutdown on SIGTERM/SIGINT.

**Apply pipeline** (`apply.apply_one`): resolve resume → skip if already applied → fetch vacancy once (drives 3 decisions: `has_test`, `employer_id`, `response_letter_required`). `has_test` → `form_filler` solves the test over the web session, but the worker **NEVER auto-submits**: it drops a `form_draft` (status `pending`) for user approval and records `form_pending`; on failure it records `form_required`. Letter required → generate cover letter (else empty message). `POST /negotiations`, then map every hh error to an `ApplyStatus` literal (`sent`/`form_sent`/`form_pending`/`form_required`/`captcha`/`token_dead`/`account_banned`/`resume_missing`/`vacancy_gone`/…). `has_test` vacancies are **not** pre-recorded or skipped by the producer — they go through the queue like everything else. The producer does auto-blacklist employers on "already applied" / non-empty `relations`.

**Retryable statuses**: `apply.RETRYABLE_STATUSES` (`{"form_required"}`) is the single source of truth for "this row never reached hh, re-evaluate later". Both `apply._already_applied` and `vacancy_producer._existing_vacancy_ids` read it — they used to disagree, which made every `form_required` row permanently unreachable. `form_pending` is NOT retryable (answers are waiting for the user).

**Form-draft approval**: `form_drafts.py` — AI-filled test answers land as a `form_drafts` row (`pending`). User reviews in the UI; `/api/forms/drafts/{id}/approve` re-fetches xsrf and POSTs to hh (`approve()`), `/discard` dismisses. `form_filler` returns answers only — submission moved here.

**Recruiter chat agent**: the recruiter loop calls `poll_recruiter_chats` (`worker/recruiter_poll.py`) → `chatik.recent_chats` (NOT legacy negotiations API — it's frozen and misses bot questions, our replies, and real-recruiter messages after the robot leaves) → `recruiter.new_employer_message` (cursor on `last_handled_id`, NOT `viewed_by_me`, to avoid double-replies) → `HHAgent.answer_recruiter` or, when the chatik message carries quick-reply buttons (`actions.text_buttons`), `answer_recruiter_choice` (same agent/tools, but the reply MUST exactly match a button label or hh loops — `recruiter_tools.match_label` maps the model's text back to the verbatim label).

**The agent never posts to hh.** All three tools (`recruiter_tools.py`) end in a row the user must act on: `answer_recruiter_question` → `recruiter_drafts` (sent by the user via `/api/recruiter/drafts/{id}/send`), `escalate_to_human` → the same table with a reason, `make_todo` → `recruiter_todos`. Each also writes a notification. Errors are logged and never crash the loop. `/api/chats` reads messages from chatik (falls back to the stale legacy API when there's no web session); manual send via `/api/chats/{id}/messages`.

Negotiation states (used only for the «Отказ» tag) are cached per user for 30 min (`recruiter_poll._STATES_TTL_S`) — the uncached version paged up to 1500 negotiations every 2 minutes per user.

**Centralized AI (`HHAgent`)**: one `HHAgent` per runner (`ai/agent.py`) wraps a single rate-limited `ChatOpenAI`. ALL LLM work routes through it — `write_form_answers` (form_filler), `write_cover_letter` (cover_letter), `answer_recruiter` / `answer_recruiter_choice` (langchain agent + `recruiter_tools.py` tools; **no checkpointer** — the caller passes the chat history every run, a saver on top of that doubled the history on each poll), `filter_relevant_vacancies` (relevance, grounded in the filter's resume summary). No per-call LLM construction. Empty `OPENAI_API_KEY` → helpers fall back to templates/heuristics, never crash. All AI text passes `prompts.sanitize_ai_text` (strips markdown bold/emphasis + em-dashes).

**Form-test solving (`form_filler.py`)**: hh vacancy tests are solved over the **hh.ru web session** (not the API) using cookies captured during OAuth login (`web_cookies_encrypted`, Fernet). Parses `vacancyTests` + `xsrfToken` out of the page's inline JSON, answers each task via the shared LLM grounded in a resume summary. No browser, no re-login. **Does not submit** — returns answers; the actual POST to `vacancy_response/popup` happens in `form_drafts.approve()` after user approval. Failure → `form_required` fallback. A free-text task with no usable LLM answer raises instead of inventing one — «Да» на «Укажите желаемый доход» хуже, чем ручное заполнение.

**Dead web session**: the cookies never refresh, so they eventually expire and both form-solving and the chat agent would silently stop working. `form_filler.session_looks_dead(resp)` (login redirect / 403) → `WebSessionExpired` → `report_dead_session` drops the cached session and fires a one-shot `web_session_expired` notification + UI banner asking for reconnect. `chatik` raises and reports the same way. Reconnect/disconnect clear the cache and re-arm the notification. Distinguish "no session stored" (never connected) from "session rejected" — only the second one notifies.

**Client / session caching**: `hh_credentials.load_api_client` caches the built `ApiClient` per user for 60s (`_CLIENT_TTL_S`) — otherwise every hh call meant a Supabase SELECT + 2 Fernet decrypts + a fresh TCP/TLS handshake. `drop_cached_client` is called from `mark_invalid` / disconnect / reconnect. The hh web session is cached for 30 min the same way, `deps.get_current_user` caches verified JWTs for 60s keyed by SHA-256 of the token. All caches are process-local — `backend/tests/conftest.py` resets them between tests.

**Cover letter cache**: `cover_letter.generate` keys on `(vacancy_id, resume_id)` in `cover_letters_cache` (PG). Hit → skip OpenAI. Miss → LLM → on failure, `rand_text` `{a|b}` template. All writes service_role.

**Analytics funnel**: `GET /api/analytics?days=` → `negotiation_sync.sync_states` (paged `GET /negotiations`, `order_by=updated_at`, writes only actual state changes so `hh_state_at` really means "when it changed"; throttled to 5 min per user, never raises) → `analytics.summary` → `analytics_summary()` in PG. Funnel: AI-checked → AI-kept → sent → viewed (`hh_viewed`) → replied (`hh_state` moved OR a `recruiter_chats` row saw an employer message) → invited (`hh_state='invitation'`). "Sent" counts only `sent`/`form_sent` rows — `form_required`/`failed`/`captcha` never reached hh and land in the failures breakdown instead. Rates are `null` when the denominator is 0; the UI prints "—", never a fake 0%. Attribution comes from `applications.filter_id` (passed `producer → ApplyJob → apply_one`) and `employer_name`, both set on new rows only — historical rows show up as "без фильтра".

**Plan → limits (no trial, migration 026)**: gating is not a gate anymore, it's "which caps apply". `plan.limits_for(profile)` → `{mode, daily, total}`: `active`/`cancelled` inside `plan_expires_at` → `auto` + `PAID_DAILY_APPLIES`/day; everything else (`free`, expired paid) → `manual` + a lifetime `FREE_TOTAL_APPLIES`. `BILLING_ENABLED=False` (self-host default) short-circuits to unlimited+auto and never reads the plan — without it a self-hoster is capped at 30 applies inside their own instance. The free total is counted straight off `applications` where `status in ('sent','form_sent')` (no counter column; `form_required`/`failed`/`captcha` never reached hh and must not burn quota) and surfaces as `limiter.check` → `"limit_total"`. `has_access` survives only as "is this a paying customer" — billing status and `require_active_plan`, which now gates just the recruiter agent, not worker start. In `manual` mode the runner does **one** producer pass, drains the queue, then clears `worker_enabled` and stops (`_finish_batch`, state `idle`) — the flag must be cleared first or `worker_main` respawns it every 15 s and "one batch" becomes the old infinite loop. `limit_total` stops the runner the same way. `worker_main` gates only the agent loop on `plan.filter_paid`; the apply loop runs for free users too.

**Billing (Polar.sh, merchant of record)**: `/api/billing/subscribe` → `billing.polar_checkout_url` creates a hosted Checkout Session with `external_customer_id = user_id` → the frontend redirects there. Polar charges the card and POSTs to `/api/webhooks/polar`, verified by the SDK's `validate_event` (Standard Webhooks — never hand-rolled HMAC; note it base64-encodes the secret internally). Events handled: `order.paid` (records the payment idempotently — Polar order id → `payments.provider_payment_id` UNIQUE — then activates), `subscription.active`/`uncanceled` (activate), `subscription.canceled` (plan `cancelled`, paid period kept), `subscription.revoked` (back to `free`, **not** to a locked account). The access window is the subscription's `current_period_end`, taken from the provider — the old code guessed it from the charged amount and could not tell two same-priced plans apart. The user is matched by `customer.external_id`. In SDK models the event type field is `TYPE` (alias `type`), so `process_polar_event` reads both. The endpoint always answers 200 once the signature is valid, or Polar retries forever. Cancellation is the Polar **customer portal** (`/api/billing/portal`), which closes the old "real cancel is manual via support" debt.

**Browser extension (`ext/`)**: the Firefox add-on fills third-party application forms — a separate surface from the hh worker, sharing the same account and Q&A memory. `snapshot.ts` (ported from OtclickUS) collects the page's fields across shadow DOM and ARIA widgets; `deterministic-fill.ts` fills verbatim facts and attaches the hh resume PDF with no LLM call; everything else goes to `POST /api/extension/fill`, where `candidate_context.build` assembles resume + `qa_memory` and `HHAgent.fill_form_fields` decides one value per field. A value that matches no real option, or that the context doesn't support, is **dropped** rather than guessed, and the extension never clicks submit. Whatever the user corrects afterwards is posted to `/api/extension/qa` and lands in the same `qa_memory` the hh form drafts read. The chat tab is stateless server-side: the transcript lives in `browser.storage.local` and travels with each request. Auth reuses the web session — a content script on the Otclick origin reads the Supabase cookie and hands it to the background (Firefox has no `externally_connectable`).

**Cron endpoints** (`/internal/cron/*`, guarded by `X-Internal-Token` compared with `hmac.compare_digest`, no JWT — trigger from system cron):
- `refresh-tokens` → `token_refresh.refresh_due`, refreshes only creds expiring within `REFRESH_THRESHOLD_DAYS` (hh refresh tokens are single-use and only usable after the access token expires).
- `prune-notifications` → `retention.prune_notifications` → the `prune_notifications` PG function (migration 025): read rows older than 14 days, anything older than 90. Without it the table grows by up to `DAILY_LIMIT` rows per user per day forever.

**Notifications**: worker events (`apply_success`, `captcha`, `limit_reached`, `token_dead`, `account_banned`, `web_session_expired`, `resume_missing`, `recruiter_draft`, `recruiter_todo`, …) insert `notifications` rows; the frontend reads them via Supabase Realtime.

**Apply counters are atomic**: `limiter.increment` calls the `increment_apply_counter(user_id, date)` RPC (migration 025, `INSERT … ON CONFLICT DO UPDATE SET count = count + 1 RETURNING count`). The old read-modify-write held only because there is exactly one runner per user; do not reintroduce it.

**Orphaned filters**: deleting a resume sets `filters.resume_id = NULL` (migration 021) and the producer skips such filters — the worker looks "running" while doing nothing. `resume_sync` now disables them (`enabled=false`) and sends a `resume_missing` notification.

**Supabase client split**: `anon_client` only for JWT validation. `service_client` for all DB/storage writes (bypasses RLS). All sync Supabase calls run in `loop.run_in_executor` — never block the event loop.

**Token credential flow**: `hh_credentials.load_api_client` decrypts tokens → builds `ApiClient` → caller saves `original_access = client.access_token` before calling hh API → after the call, `persist_if_refreshed` re-encrypts and saves if `ApiClient` auto-refreshed the token.

**Token encryption**: Fernet symmetric encryption for hh tokens in `hh_credentials` table. `service_role` key only — no user-visible access.

**hh API client**: `BaseClient` → `OAuthClient` (token exchange) + `ApiClient` (API calls with auto token refresh on 403). Thread-safe via `Lock`. Rate-limited, default 0.345s delay. hh 429 → `errors.TooManyRequests`, deliberately **not** a `ClientError` so it escapes `apply_one` and the runner treats it as transient (one retry after `RETRY_THROTTLED_SLEEP_S=60`).

## Frontend (`frontend/src/`)

Next.js App Router. Authed pages under `app/(app)/` (dashboard, applications, analytics, billing + billing/success, account, notifications, chats, todo) behind `(app)/layout.tsx`; public `auth/`, `onboarding/`, landing `page.tsx`. Supabase SSR auth split across `lib/supabase/{client,server,middleware}.ts`.

- `lib/api.ts` — `apiFetch`: attaches the Supabase session JWT as `Bearer` to every backend call (backend `deps.get_current_user` validates it). Base URL from `NEXT_PUBLIC_API_URL`.
- `hooks/` — `useHHConnect`, `useFilters`, `useBlacklist`, `useChats`, `useRecruiter`, `useFormDrafts`, `useNavCounts` wrap the backend endpoints.
- `components/otclick/` — app chrome (sidebar, worker-bar, hh-banner, captcha-banner, command-palette, onboarding-modal, qa-memory, `landing/`, shared `ui.tsx`/`icons.tsx`); top-level `captcha-modal`, `filters-drawer`, `toaster`.
- `lib/` also holds pure, unit-tested helpers (`applications-url`, `command-registry`, `nav-counts`, `status`) — `npm test` runs them in CI.
- Notifications stream in via Supabase Realtime (matches backend `notifications` inserts).

Env: `frontend/.env.local` (see `.env.local.example`) — `NEXT_PUBLIC_API_URL=http://localhost:8000` (the backend, not Kong), `NEXT_PUBLIC_SUPABASE_URL=http://localhost:54321`, anon key from `gen-keys.py`. The dockerized frontend bakes these at build time (`docker compose build frontend` after changing them).

## Supabase Tables

Migrations live in `infra/supabase/migrations/` (numbered SQL files, `001`–`025`). Applied by the `migrate` service against the local stack, tracked in `public.schema_migrations` — see Commands.

- `profiles` — user profiles + plan state (`plan`, `trial_ends`, `plan_expires_at`, `polar_customer_id`/`polar_subscription_id`, legacy `cp_subscription_id`), `worker_enabled` / `agent_enabled`, `onboarded`, `timezone`, `negotiations_synced_at`. **`authenticated` may UPDATE only `onboarded` and `timezone`** (migration 024) — every billing/worker field is service_role-only, since PostgREST is exposed to the browser through Kong
- `hh_credentials` — encrypted hh tokens + `web_cookies_encrypted` per user (full RLS denial, service_role only)
- `resumes` — user resume list synced from hh, unique on `(user_id, hh_resume_id)`; a new filter seeds its `text` from `title`
- `filters` — saved vacancy search filters per user (`name`, `ai_filter_enabled`, `relevance_criteria` — free-text user rules injected into both AI relevance stages, migration 035); `resume_id` is `ON DELETE SET NULL` (migration 021 — CASCADE used to wipe filters on reconnect). Search fields track hh's live params (migrations 029–031): `excluded_text` (hh-side word exclusion, replaced the client-side `excluded_regex`), `search_field` (default `name` — matching descriptions too was the main source of junk), `period` (default 30 days), `work_format`/`employment_form` (hh deprecated `schedule`/`employment`). No `professional_role`: it was seeded from the resume and AND-ed on top of `text`, dropping correct vacancies the employer had tagged loosely (migration 031). No salary filter: hh reads `salary` as RUR unless `currency` is passed, so a tenge number silently searched for ~4× the money
- `applications` — apply attempts/results, unique on `(user_id, vacancy_id)`; stores status, cover_letter, `form_answers`; `resume_id` is `ON DELETE SET NULL` (migration 020)
- `blacklist` — blacklisted employers per user, unique on `(user_id, employer_id)`
- `apply_counters` — per-user daily/hourly apply tallies (limiter)
- `cover_letters_cache` — generated cover letters keyed on `(vacancy_id, resume_id)`
- `vacancy_cache` — cached hh vacancy payloads
- `payments` — payment transactions (`provider='polar'`), unique on `provider_payment_id` (= Polar order id)
- `notifications` — worker→UI events (read via Realtime)
- `captcha_requests` — pending captcha challenges raised by worker
- `form_drafts` — AI-filled test answers awaiting user approval (service_role only)
- `recruiter_chats` — per-negotiation agent state/cursor (`last_handled_id`)
- `recruiter_drafts` — agent escalations awaiting human send (incl. `question_text`)
- `recruiter_todos` — agent-created todos for the user
- `worker_runtime` — runner heartbeat (state/queued/today_count/next_run_at/last_error), read by API
- `relevance_cache` — AI vacancy relevance verdicts, unique on `(resume_id, vacancy_id)`; service_role only. Migration 015 also adds `filters.ai_filter_enabled`
- `qa_memory` — user-curated Q&A (all answers from SENT forms / answered recruiter questions via `save_confirmed_answers`, plus manual entries; nothing lands here before the send succeeds), unique on `(user_id, question)`; service_role only. `services/qa_memory.prompt_block` injects it into form-test and recruiter prompts (migration 022)
- `captcha-screenshots` — Supabase Storage bucket for captcha images

Migration 023 adds analytics: `applications.hh_state`/`hh_state_at`/`hh_viewed` (mirrored negotiation state — the only honest source for "invited to interview"), `applications.filter_id`/`employer_name` (breakdown attribution), `profiles.negotiations_synced_at`, and the `analytics_summary(user_id, days)` PG function that returns every metric as one jsonb (service_role only; revoked from anon/authenticated).

Migrations 010–015 add the recruiter tables, `worker_enabled`, `form_drafts`, recruiter `question_text`, `worker_runtime`, and the relevance cache + `filters.ai_filter_enabled`. 016–022: `agent_enabled`, `onboarded`, `filters.name`, `resumes.professional_roles`, the two `ON DELETE SET NULL` fixes, `qa_memory`.

Migration 024 locks down `profiles`: `REVOKE UPDATE/INSERT/DELETE` from `anon`/`authenticated`, then `GRANT UPDATE (onboarded, timezone)` back — without it any logged-in user could `PATCH /rest/v1/profiles` themselves a paid plan. It also adds `SET search_path` to the `SECURITY DEFINER` `handle_new_user`.

Migration 025 adds two service_role-only functions: `increment_apply_counter(user_id, date)` (atomic daily cap) and `prune_notifications(read_days, keep_days)` (retention), plus an index on `notifications.created_at`.

## Tests

Tests set env vars before importing app modules (avoids pydantic-settings crash):

```python
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
# ... other required vars
# THEN import from app.*
```

Tests are unit-level (no real Supabase/Playwright). Async tests use `pytest-asyncio`. Supabase chain calls are mocked with a fluent `MagicMock` helper (see `test_filters_service.py::_fluent`). `tests/conftest.py` clears the process-local caches (API clients, web sessions, JWTs, negotiation states) between tests — a new cache must be reset there or tests leak state into each other. `test_hardening.py` / `test_hardening2.py` hold the regressions for the audit fixes; `tests/integration` and `tests/e2e` skip themselves unless the local stack (and, for e2e, the frontend on :3000) is up.

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