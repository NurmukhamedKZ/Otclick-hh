# Deploy

Three pieces deploy independently:

| Piece     | Where                     |
|-----------|---------------------------|
| Database  | Self-hosted Supabase (root docker-compose.yml) |
| Frontend  | Vercel                    |
| Backend + worker | Contabo VPS via Docker Compose |

---
**SSH access:**
```bash
ssh root@109.199.125.111
```

**Otclick path**
```bash
cd /home/app/app
```

**Docker rebuild**
```bash
docker compose -f docker-compose.yml up -d --build
```
---

## 1. Frontend → Vercel

1. Push repo to GitHub.
2. Vercel → Import Project → **Root Directory** = `frontend/`.
3. Env vars:
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - `NEXT_PUBLIC_API_URL=https://api.otclick.org`
4. Vercel → Settings → Domains → add `otclick.org` (and `www.otclick.org`). Follow Vercel's DNS instructions (apex usually A `76.76.21.21`).
5. Supabase dashboard → **Authentication → URL Configuration**:
   - Site URL: `https://otclick.org`
   - Redirect URLs: add `https://otclick.org/auth/callback`

---

## 2. Backend + worker → Contabo VPS (Ubuntu 24.04)

### One-time host setup

```bash
# Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# nginx + TLS
sudo apt update && sudo apt install -y nginx certbot python3-certbot-nginx

# App user + code
sudo adduser --disabled-password --gecos "" app
sudo -iu app git clone <your-repo> ~/app
```

### `~/app/backend/.env`

Copy `backend/.env.example` and fill in. For the local Supabase stack,
generate keys first:

```bash
python3 infra/supabase/gen-keys.py
# Paste output into backend/.env — see backend/.env.example comments
```

Critical vars:

```
# SUPABASE_URL=http://kong:8000 (in-network), keys from gen-keys.py
SUPABASE_URL=
SUPABASE_PUBLIC_URL=       # browser-reachable gateway, e.g. http://localhost:54321
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
JWT_SECRET=
ANON_KEY=
SERVICE_ROLE_KEY=
POSTGRES_PASSWORD=
FERNET_KEY=                  # ⚠ back this up offline — losing it bricks all stored hh tokens
OPENAI_API_KEY=
POLAR_ACCESS_TOKEN=
POLAR_WEBHOOK_SECRET=
POLAR_SERVER=production
POLAR_PRODUCT_SPRINT=
POLAR_PRODUCT_MONTH=
BILLING_ENABLED=true         # false = no paywall at all (self-host default)
INTERNAL_CRON_TOKEN=         # random; used by the daily refresh cron
CORS_ORIGINS=https://otclick.org,https://www.otclick.org
```

### Build & run

```bash
cd ~/app
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml ps
docker compose -f docker-compose.yml logs -f api worker
```

First build pulls Chromium (~1 GB) — ~5–10 min on Contabo.

### nginx reverse proxy

```bash
sudo cp ~/app/infra/nginx.conf /etc/nginx/sites-available/api
sudo sed -i 's/api.yourdomain.com/api.otclick.org/g' /etc/nginx/sites-available/api
sudo ln -s /etc/nginx/sites-available/api /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d api.otclick.org
```

### Daily token refresh cron

`crontab -e` as `app`:

```cron
0 4 * * * curl -fsS -X POST -H "X-Internal-Token: $(grep ^INTERNAL_CRON_TOKEN /home/app/app/backend/.env | cut -d= -f2)" https://api.otclick.org/internal/cron/refresh-tokens >> /home/app/refresh.log 2>&1
```

### DNS

- `otclick.org` → Vercel (apex A `76.76.21.21`, or CNAME per Vercel docs)
- `api.otclick.org` → VPS IPv4 (A record)

### Polar.sh

Dashboard → Webhooks → endpoint `https://api.otclick.org/api/webhooks/polar`, subscribed to
`order.paid`, `subscription.active`, `subscription.canceled`, `subscription.revoked`.
Copy the signing secret into `POLAR_WEBHOOK_SECRET` and the product ids into
`POLAR_PRODUCT_*` (they differ between the sandbox and production organisations).

---

## 3. Smoke test

```bash
curl https://api.otclick.org/health
# → {"status":"ok", ...}
```

Then on the frontend: signup → onboarding → connect hh → start worker → an application should land in the dashboard within ~1 min.

---

## Operations

### Update (after `git pull`)

```bash
cd ~/app && git pull
docker compose -f docker-compose.yml up -d --build
```

The worker restarts cleanly — `worker_main.py` traps `SIGTERM` and drains in-flight jobs.

### Logs

```bash
docker compose -f docker-compose.yml logs -f --tail=200 api
docker compose -f docker-compose.yml logs -f --tail=200 worker
```

### Rollback

```bash
git checkout <previous-sha>
docker compose -f docker-compose.yml up -d --build
```

(Or tag images per release and `docker compose up` with the old tag — recommended once you have a real release cadence.)

### Watch memory

Chromium leaks. If `docker stats` shows worker creeping past ~3 GB, restart it:

```bash
docker compose -f docker-compose.yml restart worker
```

Add Sentry + a memory alert before public launch.

---

## ⚠ Critical

- **Back up `FERNET_KEY`** somewhere offline (1Password, paper). Loss = every encrypted hh token in `hh_credentials` is unrecoverable; all users must re-onboard.
- `.env` is gitignored — never commit. The compose file mounts it via `env_file:`, not as a baked-in image layer.
- `127.0.0.1:8000` bind in compose means the API is only reachable through nginx — don't change to `0.0.0.0:8000` or you bypass TLS.
