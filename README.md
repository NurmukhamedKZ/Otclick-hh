<p align="center">
  <img src="https://raw.githubusercontent.com/NurmukhamedKZ/Otclick-hh/main/docs/assets/banner.svg" alt="Otclick" width="100%"/>
</p>

<h1 align="center">Otclick 🤖</h1>

<p align="center">
  <strong>AI-powered job application automation for hh.ru & hh.kz</strong>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#how-it-works">How It Works</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#tech-stack">Tech Stack</a> •
  <a href="#project-structure">Structure</a> •
  <a href="#contributing">Contributing</a> •
  <a href="#roadmap">Roadmap</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Next.js-16-000000?style=for-the-badge&logo=next.js&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Playwright-45ba4b?style=for-the-badge&logo=playwright&logoColor=white" />
  <img src="https://img.shields.io/badge/Supabase-3FCF8E?style=for-the-badge&logo=supabase&logoColor=white" />
  <br/>
  <img src="https://img.shields.io/github/license/NurmukhamedKZ/Otclick-hh?style=for-the-badge" />
  <img src="https://img.shields.io/github/stars/NurmukhamedKZ/Otclick-hh?style=for-the-badge" />
  <img src="https://img.shields.io/github/issues/NurmukhamedKZ/Otclick-hh?style=for-the-badge" />
</p>

<p align="center">
  Otclick is an open-source AI agent that automatically finds relevant vacancies on hh.ru/hh.kz,
  generates personalized cover letters, solves job application tests, and manages recruiter conversations —
  all without human intervention. Self-hostable. Privacy-first.
</p>

---

## Features

<table>
  <tr>
    <td width="50%">
      <h3>🔍 Smart Vacancy Search</h3>
      Create filters with keywords, location, salary, experience, schedule, and professional role.
      Optional AI relevance screening for precision targeting.
    </td>
    <td width="50%">
      <h3>✍️ AI Cover Letters</h3>
      Personalized cover letters generated per vacancy using your resume and the job description.
      Cached in PostgreSQL — regenerated only when needed.
    </td>
  </tr>
  <tr>
    <td width="50%">
      <h3>📝 Auto-Apply Engine</h3>
      Background worker with human-like behavior: log-normal delays (3–30s), session clustering (15–30 applications),
      1–2h breaks, and a daily cap (100 by default, counted atomically in Postgres).
    </td>
    <td width="50%">
      <h3>🧪 Vacancy Test Solver</h3>
      AI fills job application tests by parsing them from hh.ru pages and solving each question.
      Creates drafts for your review — you approve before submission.
    </td>
  </tr>
  <tr>
    <td width="50%">
      <h3>💬 Recruiter Chat Agent</h3>
      A separate loop (its own on/off switch) watches recruiter and hh-bot messages, and prepares an answer,
      an escalation, or a todo. <strong>It never sends anything to hh on its own</strong> — you approve every reply.
    </td>
    <td width="50%">
      <h3>🛡️ Captcha Handling</h3>
      When captchas appear, the system pauses, saves the screenshot, and notifies you.
      Solve it in the UI — the worker resumes automatically.
    </td>
  </tr>
  <tr>
    <td width="50%">
      <h3>🚫 Employer Blacklist</h3>
      Manual + automatic blacklisting. Already applied to an employer? Auto-blacklisted
      to avoid duplicate applications.
    </td>
    <td width="50%">
      <h3>📊 Real-time Dashboard</h3>
      Track applications, tests, recruiter conversations, and captchas in real time via Supabase Realtime.
    </td>
  </tr>
  <tr>
    <td width="50%">
      <h3>🔐 Privacy-first Auth</h3>
      OAuth via Playwright (browser automation — hh.ru's password grant is broken), with password
      or passwordless email-code login. Tokens encrypted with Fernet symmetric encryption.
    </td>
    <td width="50%">
      <h3>⚡ Self-hostable</h3>
      One `docker compose up` runs backend, worker, and frontend together.
      All data stays on your infrastructure.
    </td>
  </tr>
  <tr>
    <td width="50%">
      <h3>📈 Application Analytics</h3>
      Funnel view (AI-checked → sent → viewed → replied → invited) with reply/invite rates,
      breakdowns by filter/resume/cover-letter, and a failures report — powered by mirrored hh negotiation state.
    </td>
    <td width="50%">
      <h3>🦊 Firefox Autofill Extension</h3>
      Fills Google Forms, Yandex Forms and Microsoft Forms from your hh resume, attaches the resume PDF,
      and answers open questions with the same AI and Q&A memory. You review and submit — it never clicks send.
      See <a href="ext/README.md"><code>ext/</code></a>.
    </td>
  </tr>
</table>

---

## How It Works

```
                         ┌─────────────────────┐
                         │   Next.js Frontend   │
                         │  (Dashboard + Auth)  │
                         └──────────┬──────────┘
                                    │ JWT (Supabase Auth)
                         ┌──────────▼──────────┐
                         │   FastAPI Backend    │
                         │  (API + Background)  │
                         └──────┬─────────┬────┘
                                │         │
                    ┌───────────▼──┐  ┌───▼────────────┐
                    │  Supabase DB  │  │  hh.ru API      │
                    │  (PostgreSQL) │  │  + chatik.hh.ru │
                    └──────────────┘  └────────────────┘
```

### Application Flow

1. **Connect** — OAuth via headless Chromium (Playwright), password or emailed code. Authenticate once.
2. **Configure** — Create search filters. Optionally enable AI relevance filtering.
3. **Start Worker** — Flip the switch. The auto-apply loop:
   - Searches hh.ru for matching vacancies per filter (backing off when there's nothing new, to stay under hh's radar)
   - Deduplicates, checks blacklist, filters by AI relevance (optional)
   - Generates cover letters (cached, no duplicates)
   - Applies with human-like timing
   - Handles captcha → pauses → notifies → waits for you to solve
4. **Recruiter Chat** — A second, independently switchable loop reads new recruiter/bot messages and prepares a reply,
   an escalation, or a todo. Nothing is sent until you press send.
5. **Review** — Track everything in the dashboard. Approve form-draft test answers before submission.

---

## Quick Start

### Prerequisites

- Python ≥ 3.13
- Node.js ≥ 20
- [uv](https://docs.astral.sh/uv/) — Python package manager
- Docker & Docker Compose
- A hh.ru account
- (Optional) OpenAI API key — for AI features

### One-command start (recommended)

The fastest way to run everything — backend, worker, frontend, and a full
self-hosted Supabase stack (Postgres + Auth + Storage + Realtime) — is
Docker Compose:

```bash
# 1. Get the code
git clone https://github.com/NurmukhamedKZ/Otclick-hh.git
cd Otclick-hh

# 2. Write .env — every secret generated and pasted into all the slots that
#    must agree (JWT keys, Postgres password, Fernet key, cron token)
python3 infra/bootstrap.py

# 3. Build and start everything
docker compose up -d --build

# 4. Open http://localhost:3000 — sign up, connect hh, start applying
```

Nothing to fill in by hand. AI features are optional — add `OPENAI_API_KEY` to
`.env` when you want them (empty key → template fallbacks, nothing breaks).
Re-run with `--force` to rotate every secret (existing sessions and encrypted
hh tokens become unreadable).

No cloud account needed. Everything runs locally — the default path is a
self-hosted Supabase stack, not a hosted Supabase project. (If you'd rather not
run a server yourself, see [Cloud deployment](#cloud-deployment-vercel--railway--supabase-cloud)
below for a Vercel + Railway + Supabase Cloud alternative.) There is exactly **one** env file:
the repo-root `.env`. Compose reads it for its own `${...}` substitutions, the
`api`/`worker` containers get it as `env_file`, and `cd backend && uvicorn`
picks up the same file. (`frontend/.env.local` is only for running `npm run dev`
outside Docker.)

Database schema: the one-shot `migrate` service applies every
`infra/supabase/migrations/*.sql` that isn't recorded in `public.schema_migrations`
yet, on every `docker compose up` — fresh volume or existing one. Nothing to run
by hand; check what it did with:

```bash
docker compose logs migrate
docker exec -it aiautoclicker-db psql -U postgres -d postgres -c \
  "select version, applied_at from schema_migrations order by version"
```

If your database predates the ledger, the first run **baselines** it: every
migration currently on disk is recorded as applied without being replayed
(replaying them into a live DB would fail). Verify the newest ones really
landed before trusting it.

### Cloud deployment (Vercel + Railway + Supabase Cloud)

If you'd rather not run Docker Compose on your own server, the same codebase
deploys to managed platforms instead — no self-hosted Postgres/Auth/Kong stack.
This trades the "no cloud account needed" simplicity of Docker Compose for
"no server to patch or back up."

1. **Database — Supabase Cloud.** Create a project at
   [supabase.com](https://supabase.com/dashboard), then push the schema:
   ```bash
   supabase link --project-ref <your-project-ref>
   supabase db push --include-all
   ```
   In **Auth → URL Configuration**, set Site URL to your frontend's URL and
   add it to the redirect allow-list. If you don't have SMTP configured, turn
   **off** "Confirm email" (mailer autoconfirm) — otherwise sign-up dead-ends
   waiting on a confirmation email nothing sends. Grab the project URL and its
   `anon`/`service_role` keys from **Project Settings → API**.

2. **Backend — Railway.** Create two services from this repo, both building
   `backend/Dockerfile` with the **root directory set to the repo root**
   (the Dockerfile's `COPY` paths assume that build context):
   - `api` — healthcheck path `/health`, needs a public domain (`PORT=8000`).
   - `worker` — same image, override the start command to `python worker_main.py`.

   Set the same variables as `.env.example` on both services, except point
   `SUPABASE_URL` / `SUPABASE_PUBLIC_URL` at your Supabase Cloud project URL
   (there's no `kong:8000` to route through) and set `CORS_ORIGINS` to your
   frontend's domain. Railway containers can't get Docker Compose's
   `shm_size: 1gb` for Playwright's Chromium — this repo already launches it
   with `--disable-dev-shm-usage` to compensate (see `backend/app/hh/authorize.py`
   and `backend/app/hh/web_captcha.py`), so no extra config needed there.

   Deploy from your machine (no GitHub integration required — re-run this after
   every backend change):
   ```bash
   railway up --service api
   railway up --service worker
   ```

3. **Frontend — Vercel.** Import the repo with **Root Directory** set to
   `frontend/`. Set `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`,
   `NEXT_PUBLIC_API_URL` (your Railway `api` domain), and `NEXT_PUBLIC_APP_URL`
   (your Vercel domain), then deploy.

4. **Scheduled jobs.** There's no host crontab on a PaaS. The simplest fix is a
   tiny third Railway service on a cron schedule (`alpine:latest`, no HTTP port)
   whose start command `curl`s the two endpoints from
   [Scheduled jobs](#scheduled-jobs-self-hosted) below — or point any external
   cron (e.g. cron-job.org) at them instead.

### Backend-only dev

```bash
# Clone the repository
git clone https://github.com/NurmukhamedKZ/Otclick-hh.git
cd Otclick-hh

# Create virtual environment and install dependencies
uv sync
source .venv/bin/activate

# Install Playwright browser
playwright install chromium

# Configure environment (single root .env) and start the local Supabase stack
python3 infra/bootstrap.py
docker compose up -d db migrate auth rest realtime storage kong

# Start the development server
cd backend && uvicorn app.main:app --reload
```

### Frontend dev

```bash
cd frontend
npm install

# Copy and configure environment
cp .env.local.example .env.local
# Edit .env.local with the ANON_KEY from the root .env

# Start the development server
npm run dev
```

### Run the Worker

In a separate terminal:

```bash
cd backend
python worker_main.py
```

---

## Configuration

### Everything (`.env` in the repo root — see `.env.example` for the full list)

```env
# Local Supabase stack — all of these are written by: python3 infra/bootstrap.py
SUPABASE_URL=http://kong:8000
SUPABASE_PUBLIC_URL=http://localhost:54321
SUPABASE_ANON_KEY=<generated>
SUPABASE_SERVICE_ROLE_KEY=<generated>
JWT_SECRET=<generated — signs both keys above>
ANON_KEY=<same as SUPABASE_ANON_KEY>
SERVICE_ROLE_KEY=<same as SUPABASE_SERVICE_ROLE_KEY>
POSTGRES_PASSWORD=<generated>

# Encrypts hh tokens at rest — also generated
FERNET_KEY=<generated>

# AI — see "AI features" below. Empty key → fallback templates.
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5.4-nano

# Shared secret for the /internal/cron/* endpoints (token refresh, notification pruning)
INTERNAL_CRON_TOKEN=your-cron-token

# Polar.sh billing — optional for self-hosted (leave BILLING_ENABLED=false)
POLAR_ACCESS_TOKEN=
POLAR_WEBHOOK_SECRET=
POLAR_SERVER=sandbox
```

### AI features

The only value `infra/bootstrap.py` can't generate is the model key. Without it
the stack runs, but degrades:

| Feature | No `OPENAI_API_KEY` |
|---|---|
| Auto-apply | Works |
| Cover letters | Template fallback (`rand_text`) instead of AI |
| AI relevance filter | Fails open — keeps every vacancy |
| Vacancy tests | Not solved → `form_required`, fill them in by hand |
| Recruiter agent | Skips every chat |

`AI_POSITIONING` (default `balanced`) controls how far AI-generated text goes
in framing the candidate favorably in recruiter chat, vacancy tests, cover
letters and extension autofill. `full` opts into more aggressive tactics —
see `docs/spec-ai-positioning.md` and `AUDIT.md` before switching.

Any OpenAI-compatible endpoint works — `OPENAI_BASE_URL` is a base URL, not a
full path. A local model costs nothing and keeps resumes off third-party
servers:

```env
# Ollama on the host (from inside Docker use host.docker.internal)
OPENAI_BASE_URL=http://host.docker.internal:11434/v1
OPENAI_MODEL=qwen3:8b
OPENAI_API_KEY=ollama   # must be non-empty — the value itself is ignored
```

Tracing is off by default on purpose: `LANGSMITH_TRACING=true` ships resumes,
recruiter chats and test answers to a third party.

### Frontend (`frontend/.env.local`)

```env
NEXT_PUBLIC_SUPABASE_URL=http://localhost:54321
NEXT_PUBLIC_SUPABASE_ANON_KEY=<same ANON_KEY as the root .env>
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_GOOGLE_AUTH_ENABLED=false
```

### Scheduled jobs (self-hosted)

Two maintenance endpoints are meant to be called from your own cron, authenticated with
`INTERNAL_CRON_TOKEN` (no user JWT):

```bash
# daily — refresh hh tokens that are about to expire (hh refresh tokens are single-use)
curl -fsS -X POST http://127.0.0.1:8000/internal/cron/refresh-tokens \
  -H "X-Internal-Token: $INTERNAL_CRON_TOKEN"

# weekly — drop old notifications (read >14 days, anything >90 days)
curl -fsS -X POST http://127.0.0.1:8000/internal/cron/prune-notifications \
  -H "X-Internal-Token: $INTERNAL_CRON_TOKEN"
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 16 + React 19 + TypeScript + Tailwind CSS v4 |
| **Backend API** | Python 3.13 + FastAPI + Uvicorn |
| **Database** | Supabase (PostgreSQL + Auth + Realtime + Storage) |
| **hh.ru Integration** | Playwright (headless Chromium) + REST API |
| **AI/LLM** | OpenAI (GPT) via langchain |
| **Token Encryption** | Fernet (symmetric, cryptography) |
| **Billing** | Polar.sh — merchant of record (optional) |
| **Deployment** | Docker Compose (backend + worker + frontend) |
| **Package Manager** | uv (Python), npm (frontend) |

---

## Project Structure

```
otclick/
├── backend/                      # FastAPI backend + background worker
│   ├── app/
│   │   ├── main.py              # FastAPI app entrypoint
│   │   ├── config.py            # pydantic-settings configuration
│   │   ├── api/                 # REST API endpoints
│   │   │   ├── auth.py          # hh.ru OAuth connect/poll/captcha
│   │   │   ├── filters.py       # Vacancy search filters CRUD
│   │   │   ├── resumes.py       # Resume sync/list
│   │   │   ├── worker.py        # Worker start/stop/status
│   │   │   ├── forms.py         # Form draft approval
│   │   │   ├── chats.py         # Recruiter chat messages
│   │   │   ├── recruiter.py     # Recruiter escalation/todos
│   │   │   ├── analytics.py     # Funnel/KPI analytics
│   │   │   ├── billing.py       # Subscription management
│   │   │   ├── webhooks.py      # Polar webhook
│   │   │   ├── qa.py            # User-curated Q&A memory
│   │   │   ├── extension.py     # Firefox extension: context/fill/chat/qa/resume-file
│   │   │   └── internal.py      # Cron endpoints (token refresh, retention)
│   │   ├── ai/
│   │   │   ├── agent.py         # Centralized HHAgent (ChatOpenAI)
│   │   │   ├── prompts.py       # System prompts + text sanitizer
│   │   │   └── recruiter_tools.py  # LangChain tools for chats
│   │   ├── worker/
│   │   │   ├── runner.py        # Per-user apply loop + recruiter loop + registry
│   │   │   ├── recruiter_poll.py # Recruiter chat polling
│   │   │   ├── queue.py         # In-memory ApplyJob queue
│   │   │   ├── limiter.py       # Daily/hourly apply caps
│   │   │   └── throttle.py      # Human-like delays + session breaks
│   │   ├── services/            # Business logic
│   │   │   ├── apply.py         # Core apply pipeline
│   │   │   ├── form_filler.py   # Vacancy test solver (no browser)
│   │   │   ├── form_drafts.py   # Draft persistence + approval
│   │   │   ├── cover_letter.py  # AI cover letter generation
│   │   │   ├── vacancy_producer.py  # Search + dedup + queue
│   │   │   ├── relevance.py     # AI vacancy relevance filter
│   │   │   ├── chatik.py        # chatik.hh.ru web API client
│   │   │   ├── negotiation_sync.py # Mirror hh negotiation state for analytics
│   │   │   ├── analytics.py     # Funnel/KPI computation
│   │   │   ├── token_refresh.py # hh token refresh cron
│   │   │   ├── qa_memory.py     # User-confirmed answers reused in AI prompts
│   │   │   ├── retention.py     # Notification pruning
│   │   │   └── ...              # More services
│   │   ├── hh/                  # hh.ru API client
│   │   │   ├── client.py        # ApiClient + OAuthClient
│   │   │   ├── authorize.py     # Playwright OAuth flow
│   │   │   ├── errors.py        # API error hierarchy
│   │   │   └── datatypes.py     # Typed dicts
│   │   ├── db/                  # Supabase clients
│   │   └── schemas/             # Pydantic models
│   ├── tests/                   # pytest tests
│   ├── worker_main.py           # Standalone worker entrypoint
│   └── Dockerfile
├── frontend/                    # Next.js frontend
│   ├── src/
│   │   ├── app/                 # App Router pages
│   │   │   ├── (app)/           # Authenticated pages
│   │   │   ├── auth/            # Login/Signup
│   │   │   └── onboarding/      # HH account setup
│   │   ├── components/
│   │   │   └── otclick/         # UI components
│   │   ├── hooks/               # React hooks
│   │   └── lib/                 # API client, types, Supabase config
│   ├── Dockerfile
│   └── package.json
├── ext/                         # Firefox extension (WXT, MV2)
│   ├── entrypoints/             # background, content script, session adoption
│   ├── lib/                     # snapshot, form filler, panel, api client
│   ├── tests/                   # vitest units
│   └── README.md                # Setup + how it works
├── infra/
│   ├── bootstrap.py             # Writes a ready-to-run root .env (all secrets)
│   ├── nginx.conf               # Reverse proxy
│   └── supabase/
│       ├── migrate.sh           # Migration runner (ledger: public.schema_migrations)
│       ├── gen-keys.py          # JWT/anon/service keys for the local stack
│       └── migrations/          # 25 SQL migrations, applied by the `migrate` service
├── .github/workflows/ci.yml     # CI: ruff + pytest, tsc + unit tests (frontend and ext)
├── docs/                        # Documentation
├── hh-applicant-tool/           # Reference CLI tool (read-only)
├── docker-compose.yml           # Backend + worker + frontend
├── pyproject.toml               # Python project config
└── uv.lock                      # Lock file
```

---

## Contributing

We welcome contributions of all sizes! Otclick is a community-driven open-source project, and every contribution helps.

### Ways to Contribute

- **🐛 Report bugs** — Open an issue with a clear reproduction
- **💡 Feature ideas** — Start a discussion or open a feature request
- **🔧 Fix bugs** — PRs are always welcome
- **🌐 Translations** — Help translate the UI and documentation
- **📝 Documentation** — Improve guides, fix typos, add examples
- **🧪 Tests** — Increase test coverage
- **🔌 New integrations** — Support more job platforms beyond hh.ru

### Development Workflow

```bash
# Fork and clone
git clone https://github.com/NurmukhamedKZ/Otclick-hh.git
cd Otclick-hh

# Set up backend
uv sync
source .venv/bin/activate
playwright install chromium

# Set up frontend
cd frontend && npm install

# Run tests (integration/e2e auto-skip unless the local stack is running)
cd backend && python -m pytest tests/ -v

# Run linter
ruff check backend

# Frontend checks
cd frontend && npx tsc --noEmit && npm test
```

CI (`.github/workflows/ci.yml`) runs exactly these on every PR — green locally, green there.

### Guidelines

- Match existing code style (no comments beyond what's needed)
- Write tests for new functionality
- Keep PRs focused — one feature/fix per PR
- Update documentation if you change behavior
- Be kind and respectful — we follow the [Contributor Covenant](https://www.contributor-covenant.org/)

### Need Help?

- Check existing issues and discussions
- Open a new issue for questions
- Join the community (links below)

---

## Roadmap

Here are the priority tasks and future plans. Want to help? Pick one up!

### 🔥 Immediate Priority
- [x] **Update UI/UX** — Dashboard redesigned for better usability and a modern look
- [x] **Fix Form Filling** — Vacancy form-filling pipeline debugged and stabilized (AI-filled drafts you approve before submission)
- [ ] **Google, MS Teams, Yandex forms autofilling** — Extend autofill support beyond hh.ru built-in tests to external Google Forms, Microsoft Forms, and Yandex Forms used by employers
- [ ] **Fix AI agent session persistence** — The hh web session (cookies captured at login) still expires and can only be restored by reconnecting. Expiry is now *detected* and you get a notification + banner instead of silent failure, but automatic renewal is not implemented
- [x] **Unified Docker setup** — Single `docker compose` file that runs backend, worker, and frontend together for one-command deployment

### 📋 Future
- [ ] **Multi-language support** — Internationalization (i18n) for the dashboard
- [ ] **More job platforms** — LinkedIn, Indeed, Glassdoor integrations
- [x] **Application analytics** — Funnel, KPIs, and breakdowns on your applications
- [ ] **Cover letter templates** — Customizable templates with variables
- [ ] **AI interview prep** — Generate likely interview questions based on the vacancy
- [ ] **Scheduling** — Set specific hours for the worker to run
- [ ] **Email notifications** — Get notified without checking the dashboard
- [ ] **Native mobile app** — React Native or Flutter companion app
- [ ] **WebSocket live logs** — Real-time worker log streaming in the UI
- [ ] **Plugin system** — Extend the worker with custom hooks

---

## Community & Support

- 💬 **Discussions** — GitHub Discussions for Q&A and ideas
- 🐛 **Issues** — GitHub Issues for bugs and feature requests
- 📖 **Documentation** — Check the `docs/` directory
- 🤝 **Contributing** — See [CONTRIBUTING.md](CONTRIBUTING.md) (coming soon)

---

## Sponsors

If Otclick saves you time or helps you land a job, consider sponsoring the project. Sponsorships go toward hosting costs, development time, and community rewards.

[Become a sponsor](https://github.com/sponsors/NurmukhamedKZ)

---

## License

This project is open source under the [MIT License](LICENSE).

---

<p align="center">
  <strong>Otclick</strong> — Because applying to 100+ jobs shouldn't take 100+ hours.
  <br/>
  Made for developers who'd rather code than copy-paste cover letters.
</p>
