# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Otclick** (public repo: **https://github.com/NurmukhamedKZ/Otclick-hh**, MIT license — this is the canonical URL for clones, badges and README links; the older `NurmukhamedKZ/Otclick` name is stale) — open-source AI agent for hh.ru/hh.kz job application automation. Self-hostable, privacy-first. See `README.md` for the public-facing pitch, feature list, and roadmap. Sub-projects:

- **`backend/`** — FastAPI service (active build) + standalone worker (`worker_main.py`)
- **`frontend/`** — Next.js 16 + React 19 + Tailwind v4 (Supabase SSR auth)
- **`hh-applicant-tool/`** — existing Python CLI tool (source to copy from, not modify)
- **`ext/`** — Firefox extension (WXT, MV2): autofills Google/Yandex/MS Forms + an AI chat tab, served by `/api/extension/*`. Forked from `extension/` (a gitignored copy of the OtclickUS extension kept as a porting source — never edit that copy). See `ext/README.md`
- **`AUDIT.md`** — production-readiness audit: what's fixed, what's still open. Its billing entries are obsolete: there is no billing in this build (see "No billing"). Read it before shipping anything near the worker.

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

There is **no hosted Supabase project** anymore — the stack in `docker-compose.yml` (Postgres + Auth + Kong + Storage + Realtime) is the single environment for dev and for the default self-host path. A self-hoster who'd rather not run that stack on their own server can instead point the app at their own Supabase Cloud project (README's [Cloud deployment](README.md#cloud-deployment-vercel--railway--supabase-cloud) section) — everything below about `migrate.sh`/Kong/dual URLs is specific to the self-hosted stack and doesn't apply there (Supabase Cloud has one URL, its own dashboard-issued keys, and migrations go through `supabase db push` instead). Consequences (self-hosted stack only):

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
# function_calling is portable across OpenAI-compatible providers; json_schema
# only where the provider really implements OpenAI Structured Outputs.
OPENAI_STRUCTURED_OUTPUT_METHOD=function_calling

# hh OAuth app. Empty → the official Android app's borrowed keys, which answer
# `error=geo_forbidden` on /oauth/authorize outside their region (login succeeds,
# hh then refuses the code). Fix: your own app on dev.hh.ru/admin or dev.hh.kz/admin.
# All three move together; HH_REDIRECT_URI must match the registration byte for byte.
HH_CLIENT_ID=
HH_CLIENT_SECRET=
HH_REDIRECT_URI=

# cron endpoints (shared secret for /internal/cron/*: refresh-tokens, prune-notifications)
INTERNAL_CRON_TOKEN=

# Hard kill switch for every real response to hh (see "Two-key send gate").
# Discovery, scoring, review and cover-letter drafts all work with it false.
ALLOW_REAL_APPLY=false
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
  worker.py                  — /api/worker/* (start/stop apply loop, agent/start|stop, flags/{flag}, status)
  qa.py                      — /api/qa (list/upsert/delete user-curated Q&A memory)
  forms.py                   — /api/forms/drafts (list, approve→post to hh, discard)
  chats.py                   — /api/chats (list negotiations, get messages, send message)
  recruiter.py               — /api/recruiter (escalation drafts send/discard, todos done/dismiss)
  analytics.py               — /api/analytics?days= (syncs hh negotiation states, then one RPC)
  search_sources.py          — /api/search-sources/* (CRUD, URL preview, manual run + run poll)
  vacancies.py               — /api/vacancies/* (backlog, decision, enrich, cover letter, maintenance, calibration)
  selection_rules.py         — /api/selection-rules/* (proposals, approve/reject, toggle, rescore/archive impact)
  send_queue.py              — /api/send-queue/* (queue/cancel/reset, bulk, sender control)
  candidate_context.py       — /api/candidate-context (what the funnel actually knows about the candidate)
  extension.py               — /api/extension/* (context, fill, chat, qa, resume-file) for the Firefox extension
  internal.py                — /internal/cron/* (X-Internal-Token via hmac.compare_digest, no JWT) → refresh-tokens, prune-notifications
  _debug.py                  — debug-only routes, mounted iff DEBUG_ENDPOINTS
  router.py                  — aggregates all routers
ai/
  openai_compat.py           — CompatibleChatOpenAI (portable structured output) + provider headers
  cover_letter_prompt.py     — the rich v2 cover-letter system prompt
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
  # ── vacancy funnel (sources → scoring → rules → queue → statistics) ──
  search_sources.py          — pure hh search-URL parser (keeps duplicate query keys)
  search_source_service.py   — sources CRUD + per-source outcome stats
  source_discovery.py        — paginate hh search over the web session → vacancy_pipeline
  source_statistics.py       — atomic cumulative per-source counters (RPC)
  vacancy_pipeline.py        — persistence + optimistic transitions + scoring claim leases
  vacancy_review_service.py  — backlog/read model, full-page enrichment, user decisions
  pipeline_scoring.py        — hard filter (rules + blacklist) → structured LLM score
  pipeline_cover_letters.py  — structured rich draft, generate/save, approval invalidation
  pipeline_maintenance.py    — rescore stale, retry incomplete, regenerate stale covers, bulk archive
  selection_rules.py         — LLM rule proposals from a reject + approval → active versioned rule
  selection_rule_actions.py  — rule toggle/delete/regenerate + rescore/archive impact
  send_queue_service.py      — exact-text (SHA-256) approval + durable send jobs
  send_runtime_control.py    — sender batches, desired_state, DB lease + progress
  bulk_send_queue.py         — explicit bulk queueing of approved letters
  persistent_sender.py       — leased sender loop (still behind the two-key send gate)
  search_run_service.py      — durable manual discovery/scoring runs (search_runs)
  calibration_report.py      — score vs. the user's actual decisions
  context_fingerprints.py    — deterministic score/cover context hashes → stale detection
  candidate_context_service.py — candidate context built from the user's resume + qa_memory
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
  plan.py                    — compatibility shim: no commercial quotas, everyone is "auto"/unlimited
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
  auth.py, resumes.py, filters.py, blacklist.py, recruiter.py — Pydantic models
  vacancies.py, search_sources.py, selection_rules.py, send_queue.py,
  candidate_context.py, calibration.py — funnel models
```

## Key Design Patterns

**OAuth job flow**: `POST /api/hh/connect` → creates async job (UUID) → returns immediately → client polls `GET /api/hh/connect/{job_id}`. Job runs Playwright in a background task whose reference is kept on `JobState.task` (a bare `create_task` can be GC'd mid-flow). Passwordless variant: the same job pauses for the emailed code, submitted via `POST /api/hh/connect/{job_id}/code`. Admission control in `hh_auth._admit`: **one live job per user, `MAX_CONCURRENT_JOBS=4` globally** (429 otherwise) — each job is a headless Chromium. Finished jobs are purged after `FINISHED_JOB_TTL_S=600`. `_jobs` is process-local, so the API must run as a single process (or job state has to move to the DB).

**Chromium shm on PaaS deploys**: all three `pw.chromium.launch(...)` calls (`hh/authorize.py` x2, `hh/web_captcha.py`) pass `args=["--disable-dev-shm-usage"]`. Docker Compose covers Playwright's `/dev/shm` need with `shm_size: 1gb` (see `docker-compose.yml`), but a platform like Railway gives no way to set that, and the default 64MB crashes Chromium mid-OAuth/captcha — the launch flag is the fix, keep it even though it looks redundant next to the compose `shm_size`.

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

**No billing.** Polar checkout, webhooks, plan gating and free/paid apply quotas were removed. `services/plan.py` survives as a compatibility shim (`has_access` → True, `limits_for` → `{"mode": "auto", "daily": None, "total": None}`) and `worker/limiter.py` keeps only the counters (`increment_apply_counter` RPC, `sent_total`) for status and analytics. `limiter.check` always returns `"allowed"`; the guard that actually matters is the two-key send gate below. `profiles` keeps its historical plan columns — nothing reads them.

## Vacancy funnel: sources → scoring → rules → queue → statistics

A persistent funnel in PostgreSQL, separate from the legacy `vacancy_producer → ApplyJob → apply_one` loop and independent of it. `asyncio.Queue` is not the source of truth here; `vacancy_pipeline` is. Migrations `035`, `037`–`045`.

**1. Sources** (`search_sources.py` — pure parser, `search_source_service.py` — CRUD, `source_discovery.py` — the worker half). The user pastes an hh.ru/hh.kz search URL; it is parsed into an **ordered list of `{key, value}` pairs**, not an object — hh repeats `area`/`professional_role`/`search_field`, and a dict would silently drop all but the last. Discovery walks `GET /search/vacancy` over the **web session** (`hh/web.py` + `find_state("vacancySearchResult")`), forcing `order_by=publication_time`. The cursor is the previous run's first-page ids (`cursor.head_ids`): the scan stops at the first overlap — 3 pages on a first run, up to 20 incrementally, and `cursor_overlap_not_found_within_scan_limit` is recorded when even 20 pages did not reach known ground. Vacancies the user already applied to are skipped; everything else is upserted into `vacancy_pipeline` (unique on `(user_id, hh_vacancy_id)`) plus a `vacancy_pipeline_sources` link row, so one vacancy found by three sources is stored once and still attributed to all three.

**2. Scoring** (`pipeline_scoring.py`). `MAX_SCORE_PER_RUN=15` per cycle. Each row is claimed with a **lease token** (`vacancy_pipeline.claim_for_scoring` → uuid, 10-minute lease): every terminal write carries `expected_claim_token`, so a reaped or superseded scorer cannot overwrite a newer attempt or a user's decision. Order: full-page enrichment → hard filter → structured LLM score → `scored` / `rejected_by_rule` / `score_error`. The score is four components of 0–25 (`role_fit`, `seniority_scale_fit`, `requirements_match`, `context_fit`) summed by the application, never by the model, plus pros/risks/unknowns/confidence. Transient hh failures (`web.HHTransientError`, raised after the bounded retry in `hh/web.py`) send the row back to `discovered` with `next_score_at` 60 s → 300 s, at most `MAX_TRANSIENT_SCORE_ATTEMPTS=3`; two consecutive transient failures open a per-run circuit breaker instead of burning the whole batch. `reap_expired_vacancy_scoring()` (RPC, called at the top of every worker pass) recovers orphaned claims and turns the third expiry into a visible `score_error`.

Automatic rejects are **explainable and user-derived only**: approved `hard_reject` rules and the existing employer `blacklist`. `auto_reject_details` stores a snapshot per condition (which rule, which version, which terms matched), so the UI can say *why*. There is no hardcoded profession list — fit criteria come from the account's own data.

**Candidate context** (`candidate_context_service.py`) is what grounds scoring, cover letters and rule proposals: the newest synced resume (`form_filler.load_resume` + `_resume_summary`) plus `qa_memory`, shaped as `{version, source_name, profile, facts}` with a stable `fact_key` per fact (`experience_N`, `skills`, `about`, `qa_N`). `version` is derived from `resumes.synced_at`, so re-syncing a resume correctly marks old scores and letters stale. No candidate tables, nothing to seed.

**3. Rules** (`selection_rules.py`, `selection_rule_actions.py`). When the user rejects a vacancy with a reason, the LLM may propose a rule (`hard_reject` or `scoring_preference`) with an impact preview — a `vacancy_rule_proposals` row, never an active rule. Only explicit approval creates a versioned `vacancy_selection_rules` row. Rules are soft-deleted (`deleted_at`) and can be superseded (`superseded_by_rule_id`) so a score's `applied_rule_versions` stays meaningful. Scoring sees active, non-deleted, matching rules only; proposals are invisible to it.

**4. Queue** (`send_queue_service.py`, `send_runtime_control.py`, `persistent_sender.py`, `bulk_send_queue.py`). `pipeline_cover_letters.generate_draft` writes a structured rich draft (assembled by the application from explicit blocks, so a model cannot satisfy the contract with two sentences) whose `cover_letter_meta` cites the `fact_key`s it used. Approval stores the **SHA-256 of the exact text**; editing the letter clears the approval, and an approved letter cannot be edited while its send job is live. Queued jobs are durable rows in `application_send_queue` (unique per vacancy), grouped into `application_send_batches` and driven by `application_send_control.desired_state` (`paused` / `running` / `stop_after_current`) under a Postgres lease (`acquire_application_send_lease`) that enforces one sender per account and a `safety_interval_seconds` between cycles.

**Two-key send gate.** `settings.ALLOW_REAL_APPLY` (deployment, `.env`) **and** `profiles.real_apply_enabled` (per user, UI switch) must both be on or nothing reaches hh. The check lives in `form_filler.submit_response`, which is the single choke point every real submit routes through — the legacy apply loop, approved form drafts and the funnel sender alike. Do not add a second submit path that bypasses it.

**5. Statistics.** Per-source cumulative counters (`vacancy_search_sources.stats`: new / duplicate / hard_filtered / score_error) are bumped through the atomic `increment_vacancy_source_stats` RPC, kept separate from the cursor so discovery and scoring can write concurrently. `search_source_service` adds current per-source outcome breakdowns, `pipeline_maintenance.get_status` reports stale/incomplete counts, and `calibration_report.py` compares the score against the user's actual accept/reject decisions. UI: `/vacancies/sources`, `/vacancies/stats`.

**Manual runs** (`search_run_service.py`, migration 042). `POST /api/search-sources/run-now` does not run hh in the API process: it enqueues a `search_runs` row the worker claims via `claim_next_search_run()`. A partial unique index allows one active run per user (a double-click or second tab cannot start two concurrent hh cycles), and a claimed run older than two hours is failed as a crash recovery so the index can never wedge the account.

**Runtime switches** (`worker_control.py`, migration 045). Every switch is persisted in `profiles` and flipped from the UI, never from env or a console: `apply` (`worker_enabled`, the legacy auto-apply runner), `discovery` (`discovery_enabled`, the funnel's discovery + scoring cycle, every `DISCOVERY_INTERVAL_S=5 min`), `agent` (`agent_enabled`) and `real_apply` (`real_apply_enabled`). `worker_main._reconcile` reads all of them in one pass (`active_user_flags`), recovers expired scoring leases, runs at most one manual search job, and reconciles the per-user runners. The three loops are independent: none implies another.

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

Next.js App Router. Authed pages under `app/(app)/` (dashboard, vacancies, applications, analytics, account, notifications, chats, todo) behind `(app)/layout.tsx`; public `auth/`, `onboarding/`, landing `page.tsx`. Supabase SSR auth split across `lib/supabase/{client,server,middleware}.ts`.

- `lib/api.ts` — `apiFetch`: attaches the Supabase session JWT as `Bearer` to every backend call (backend `deps.get_current_user` validates it). Base URL from `NEXT_PUBLIC_API_URL`.
- `hooks/` — `useHHConnect`, `useFilters`, `useBlacklist`, `useChats`, `useRecruiter`, `useFormDrafts`, `useNavCounts` wrap the backend endpoints.
- `app/(app)/vacancies/` — the funnel UI: review backlog (`page.tsx` + `cover-letter-editor.tsx`), `sources/`, `rules/` + `rules/manage/`, `send/` + `sender-control.tsx` + `send-problems.tsx`, `bulk/`, `run/`, `stats/`, `profile/` (what the funnel knows about the candidate). `layout.tsx` holds the section nav.
- `components/otclick/worker-bar.tsx` — the runtime switches: автоотклик, ИИ-агент, and in the ⋯ menu «Поиск вакансий» (discovery) and «Реальная отправка» (`POST /api/worker/flags/{flag}?enabled=`).
- `components/otclick/` — app chrome (sidebar, worker-bar, hh-banner, captcha-banner, command-palette, onboarding-modal, qa-memory, `landing/`, shared `ui.tsx`/`icons.tsx`); top-level `captcha-modal`, `filters-drawer`, `toaster`.
- `lib/` also holds pure, unit-tested helpers (`applications-url`, `command-registry`, `nav-counts`, `status`) — `npm test` runs them in CI.
- Notifications stream in via Supabase Realtime (matches backend `notifications` inserts).

Env: `frontend/.env.local` (see `.env.local.example`) — `NEXT_PUBLIC_API_URL=http://localhost:8000` (the backend, not Kong), `NEXT_PUBLIC_SUPABASE_URL=http://localhost:54321`, anon key from `gen-keys.py`. The dockerized frontend bakes these at build time (`docker compose build frontend` after changing them).

## Supabase Tables

Migrations live in `infra/supabase/migrations/` (numbered SQL files, `001`–`025`). Applied by the `migrate` service against the local stack, tracked in `public.schema_migrations` — see Commands.

- `profiles` — user profiles + runtime switches `worker_enabled` / `discovery_enabled` / `agent_enabled` / `real_apply_enabled` (migration 045), `onboarded`, `timezone`, `negotiations_synced_at`, plus dead plan columns kept by older migrations. **`authenticated` may UPDATE only `onboarded` and `timezone`** (migration 024) — every switch is service_role-only and moves through `/api/worker/*`, since PostgREST is exposed to the browser through Kong
- `hh_credentials` — encrypted hh tokens + `web_cookies_encrypted` per user (full RLS denial, service_role only)
- `resumes` — user resume list synced from hh, unique on `(user_id, hh_resume_id)`; a new filter seeds its `text` from `title`
- `filters` — saved vacancy search filters per user (`name`, `ai_filter_enabled`); `resume_id` is `ON DELETE SET NULL` (migration 021 — CASCADE used to wipe filters on reconnect). Search fields track hh's live params (migrations 029–031): `excluded_text` (hh-side word exclusion, replaced the client-side `excluded_regex`), `search_field` (default `name` — matching descriptions too was the main source of junk), `period` (default 30 days), `work_format`/`employment_form` (hh deprecated `schedule`/`employment`). No `professional_role`: it was seeded from the resume and AND-ed on top of `text`, dropping correct vacancies the employer had tagged loosely (migration 031). No salary filter: hh reads `salary` as RUR unless `currency` is passed, so a tenge number silently searched for ~4× the money
- `applications` — apply attempts/results, unique on `(user_id, vacancy_id)`; stores status, cover_letter, `form_answers`; `resume_id` is `ON DELETE SET NULL` (migration 020)
- `blacklist` — blacklisted employers per user, unique on `(user_id, employer_id)`
- `apply_counters` — per-user daily/hourly apply tallies (limiter)
- `cover_letters_cache` — generated cover letters keyed on `(vacancy_id, resume_id)`
- `vacancy_cache` — cached hh vacancy payloads
- `payments` — legacy payment table from migrations 006/027; no code reads or writes it
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

Vacancy funnel tables (migrations 035, 037–045; all service_role only, RLS on with no anon/authenticated policy — the browser must go through the API so lifecycle transitions and approval cannot be bypassed via PostgREST):

- `vacancy_search_sources` — a saved hh search: `query_pairs` (ordered array, duplicate keys preserved), `cursor` (opaque, currently `head_ids` + last-run stats), `stats` (cumulative counters), `enabled`, last checked/success/error
- `vacancy_pipeline` — one row per `(user_id, hh_vacancy_id)`: snapshot, `status` (16 states from `discovered` to `sent`), `score`/`score_details`/`score_explanation`, `hard_filter_reason`/`auto_reject_details`, `cover_letter_draft`/`cover_letter_meta`/`approved_letter_hash`, retry state (`score_attempts`, `next_score_at`, `last_score_error`) and lease state (`score_claim_token`, `score_lease_expires_at`, `score_lease_failures`)
- `vacancy_pipeline_sources` — which sources found a vacancy (many-to-many)
- `vacancy_rule_proposals` / `vacancy_selection_rules` — proposed vs. approved selection rules; rules are versioned, soft-deletable and supersedable
- `application_send_queue` / `application_send_batches` / `application_send_control` — durable approved send jobs, their batch, and the per-user sender state + DB lease
- `search_runs` — durable manual discovery/scoring runs; one active run per user (partial unique index)
- `cover_letters_cache.prompt_version` (migration 043) — invalidates letters generated by the old short prompt

Migration 023 adds analytics: `applications.hh_state`/`hh_state_at`/`hh_viewed` (mirrored negotiation state — the only honest source for "invited to interview"), `applications.filter_id`/`employer_name` (breakdown attribution), `profiles.negotiations_synced_at`, and the `analytics_summary(user_id, days)` PG function that returns every metric as one jsonb (service_role only; revoked from anon/authenticated).

Migrations 010–015 add the recruiter tables, `worker_enabled`, `form_drafts`, recruiter `question_text`, `worker_runtime`, and the relevance cache + `filters.ai_filter_enabled`. 016–022: `agent_enabled`, `onboarded`, `filters.name`, `resumes.professional_roles`, the two `ON DELETE SET NULL` fixes, `qa_memory`.

Migration 024 locks down `profiles`: `REVOKE UPDATE/INSERT/DELETE` from `anon`/`authenticated`, then `GRANT UPDATE (onboarded, timezone)` back — without it any logged-in user could `PATCH /rest/v1/profiles` themselves a runtime switch (and, back when billing existed, a paid plan). It also adds `SET search_path` to the `SECURITY DEFINER` `handle_new_user`.

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