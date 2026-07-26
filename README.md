<p align="center">
  <img src="https://raw.githubusercontent.com/NurmukhamedKZ/Otclick/main/docs/assets/banner.svg" alt="Otclick" width="100%"/>
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
  <img src="https://img.shields.io/github/license/NurmukhamedKZ/Otclick?style=for-the-badge" />
  <img src="https://img.shields.io/github/stars/NurmukhamedKZ/Otclick?style=for-the-badge" />
  <img src="https://img.shields.io/github/issues/NurmukhamedKZ/Otclick?style=for-the-badge" />
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
      1–2h breaks, daily caps (~25–30). No pattern detection risk.
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
      Autonomous AI agent monitors recruiter messages, drafts responses, can escalate to you, or create todos.
      Never misses a follow-up.
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
      OAuth via Playwright (browser automation — hh.ru's password grant is broken).
      Tokens encrypted with Fernet symmetric encryption.
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

1. **Connect** — OAuth via headless Chromium (Playwright). Authenticate once.
2. **Configure** — Create search filters. Optionally enable AI relevance filtering.
3. **Start Worker** — Flip the switch. The background worker:
   - Searches hh.ru for matching vacancies per filter
   - Deduplicates, checks blacklist, filters by AI relevance (optional)
   - Generates cover letters (cached, no duplicates)
   - Applies with human-like timing
   - Handles captcha → pauses → notifies → waits for you to solve
4. **Recruiter Chat** — The AI agent monitors incoming recruiter messages and responds autonomously, escalates, or creates todos.
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
# 1. Generate JWT/API keys for the local Supabase stack
python3 infra/supabase/gen-keys.py

# 2. One env file for everything — copy and fill it in (see .env.example)
cp .env.example .env
# Paste JWT_SECRET/ANON_KEY/SERVICE_ROLE_KEY into the matching vars,
# copy ANON_KEY → SUPABASE_ANON_KEY + NEXT_PUBLIC_SUPABASE_ANON_KEY,
# SERVICE_ROLE_KEY → SUPABASE_SERVICE_ROLE_KEY
# Set POSTGRES_PASSWORD and FERNET_KEY

# 3. Build and start everything
docker compose up -d --build

# 4. Open http://localhost:3000 — sign up, connect hh, start applying
```

No cloud account needed. Everything runs locally — there is no hosted Supabase
project, this stack is the only environment. There is exactly **one** env file:
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

### Backend-only dev

```bash
# Clone the repository
git clone https://github.com/NurmukhamedKZ/Otclick.git
cd otclick

# Create virtual environment and install dependencies
uv sync
source .venv/bin/activate

# Install Playwright browser
playwright install chromium

# Generate keys and configure environment (single root .env)
python3 infra/supabase/gen-keys.py
cp .env.example .env
# Fill in the generated keys and start the local Supabase stack:
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
# Edit .env.local with your ANON_KEY from gen-keys.py

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
# Local Supabase stack — generate keys with: python3 infra/supabase/gen-keys.py
SUPABASE_URL=http://kong:8000
SUPABASE_PUBLIC_URL=http://localhost:54321
SUPABASE_ANON_KEY=<paste ANON_KEY from gen-keys.py>
SUPABASE_SERVICE_ROLE_KEY=<paste SERVICE_ROLE_KEY from gen-keys.py>
JWT_SECRET=<paste JWT_SECRET from gen-keys.py>
ANON_KEY=<same as SUPABASE_ANON_KEY>
SERVICE_ROLE_KEY=<same as SUPABASE_SERVICE_ROLE_KEY>
POSTGRES_PASSWORD=<any strong local secret>

# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FERNET_KEY=your-fernet-key

# AI — all fields optional. Empty → fallback templates.
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o

# Internal auth for cron
INTERNAL_CRON_TOKEN=your-cron-token

# CloudPayments billing — optional for self-hosted
CLOUDPAYMENTS_PUBLIC_ID=
CLOUDPAYMENTS_API_SECRET=
```

### Frontend (`frontend/.env.local`)

```env
NEXT_PUBLIC_SUPABASE_URL=http://localhost:54321
NEXT_PUBLIC_SUPABASE_ANON_KEY=<paste ANON_KEY from gen-keys.py>
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_GOOGLE_AUTH_ENABLED=false
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
| **Billing** | CloudPayments (optional) |
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
│   │   │   ├── webhooks.py      # CloudPayments webhook
│   │   │   └── internal.py      # Cron job endpoints
│   │   ├── ai/
│   │   │   ├── agent.py         # Centralized HHAgent (ChatOpenAI)
│   │   │   ├── prompts.py       # System prompts + text sanitizer
│   │   │   └── recruiter_tools.py  # LangChain tools for chats
│   │   ├── worker/
│   │   │   ├── runner.py        # Per-user apply loop + registry
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
├── infra/
│   ├── nginx.conf               # Reverse proxy
│   └── supabase/migrations/     # 23 SQL migrations (apply with psql, see Quick Start)
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
git clone https://github.com/NurmukhamedKZ/Otclick.git
cd otclick

# Set up backend
uv sync
source .venv/bin/activate
playwright install chromium

# Set up frontend
cd frontend && npm install

# Run tests
cd backend && python -m pytest tests/ -v

# Run linter
ruff check .
```

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
- [ ] **Update UI/UX** — Redesign the dashboard for better usability and modern look
- [ ] **Fix Form Filling** — Debug and stabilize the vacancy form-filling pipeline
- [ ] **Google, MS Teams, Yandex forms autofilling** — Extend autofill support beyond hh.ru built-in tests to external Google Forms, Microsoft Forms, and Yandex Forms used by employers
- [ ] **Fix AI agent session persistence** — Resolve bug where AI agent and autofilling stop working the next day (token/session expiry issue)
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
