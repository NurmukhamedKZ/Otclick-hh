"""End-to-end smoke tests against the running local self-hosted Supabase stack.

Needs `docker compose up -d` and a root `.env` (see frontend/.env.local.example +
backend/.env.example). The whole module auto-skips when the stack isn't reachable, so
`pytest tests/` stays green on a machine with nothing running.

These hit real services — Kong, GoTrue, PostgREST, Storage, and the FastAPI backend —
because the cloud→local migration broke exactly the seams that mocks paper over:
gateway routing, JWT secret agreement, migrations, and bucket provisioning.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[3]
KONG_URL = "http://localhost:54321"
API_URL = "http://localhost:8000"
BUCKET = "captcha-screenshots"
TIMEOUT = 10

# Every table the app writes to — proves infra/supabase/migrations ran on first boot.
EXPECTED_TABLES = [
    "profiles",
    "hh_credentials",
    "resumes",
    "filters",
    "applications",
    "blacklist",
    "apply_counters",
    "cover_letters_cache",
    "vacancy_cache",
    "payments",
    "notifications",
    "captcha_requests",
    "form_drafts",
    "recruiter_chats",
    "recruiter_drafts",
    "recruiter_todos",
    "worker_runtime",
    "relevance_cache",
]


def _load_root_env() -> dict[str, str]:
    path = REPO_ROOT / ".env"
    if not path.exists():
        return {}
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


ENV = _load_root_env()
ANON_KEY = ENV.get("ANON_KEY", "")
SERVICE_ROLE_KEY = ENV.get("SERVICE_ROLE_KEY", "")
JWT_SECRET = ENV.get("JWT_SECRET", "")


def _reachable(url: str) -> bool:
    try:
        requests.get(url, timeout=3)
        return True
    except requests.RequestException:
        return False


pytestmark = pytest.mark.skipif(
    not (ANON_KEY and SERVICE_ROLE_KEY and JWT_SECRET)
    or not _reachable(f"{KONG_URL}/auth/v1/health")
    or not _reachable(f"{API_URL}/health"),
    reason="local Supabase stack not running (docker compose up -d) or root .env missing keys",
)


def _svc_headers() -> dict[str, str]:
    return {"apikey": SERVICE_ROLE_KEY, "Authorization": f"Bearer {SERVICE_ROLE_KEY}"}


def _mint_jwt(user_id: str, secret: str) -> str:
    """Hand-sign a GoTrue-shaped HS256 token — the same shape the frontend sends."""

    def b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    now = int(time.time())
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = b64(
        json.dumps(
            {
                "sub": user_id,
                "role": "authenticated",
                "aud": "authenticated",
                "iat": now,
                "exp": now + 3600,
            },
            separators=(",", ":"),
        ).encode()
    )
    signing_input = header + b"." + payload
    sig = b64(hmac.new(secret.encode(), signing_input, hashlib.sha256).digest())
    return (signing_input + b"." + sig).decode()


# --- gateway + services ------------------------------------------------------------


def test_kong_routes_auth():
    res = requests.get(f"{KONG_URL}/auth/v1/health", timeout=TIMEOUT)
    assert res.status_code == 200


def test_kong_routes_postgrest_with_anon_key():
    res = requests.get(
        f"{KONG_URL}/rest/v1/",
        headers={"apikey": ANON_KEY, "Authorization": f"Bearer {ANON_KEY}"},
        timeout=TIMEOUT,
    )
    assert res.status_code == 200


def test_kong_rejects_postgrest_without_key():
    res = requests.get(f"{KONG_URL}/rest/v1/profiles?select=id&limit=1", timeout=TIMEOUT)
    assert res.status_code in (401, 400)


def test_backend_health_reports_db_connected():
    res = requests.get(f"{API_URL}/health", timeout=TIMEOUT)
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "db": True}


# --- migrations --------------------------------------------------------------------


@pytest.mark.parametrize("table", EXPECTED_TABLES)
def test_migrations_created_table(table):
    res = requests.get(
        f"{KONG_URL}/rest/v1/{table}?select=*&limit=0",
        headers=_svc_headers(),
        timeout=TIMEOUT,
    )
    assert res.status_code == 200, f"table {table} missing — migrations did not run: {res.text}"


def test_rls_blocks_hh_credentials_for_anon():
    """hh_credentials holds Fernet-encrypted tokens — service_role only, full RLS denial."""
    res = requests.get(
        f"{KONG_URL}/rest/v1/hh_credentials?select=user_id&limit=1",
        headers={"apikey": ANON_KEY, "Authorization": f"Bearer {ANON_KEY}"},
        timeout=TIMEOUT,
    )
    assert res.status_code != 200 or res.json() == []


# --- storage (captcha screenshots) -------------------------------------------------


def test_captcha_bucket_exists():
    res = requests.get(f"{KONG_URL}/storage/v1/bucket/{BUCKET}", headers=_svc_headers(),
                       timeout=TIMEOUT)
    assert res.status_code == 200, f"bucket {BUCKET} missing: {res.text}"
    assert res.json()["public"] is False


def test_screenshot_upload_sign_and_fetch_round_trip():
    """Mirrors hh_auth.on_captcha: upload PNG → signed URL → browser fetches it."""
    path = f"test-{uuid.uuid4()}.png"
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001080600000"
        "01f15c4890000000a49444154789c6300010000050001"
        "0d0a2db40000000049454e44ae426082"
    )

    upload = requests.post(
        f"{KONG_URL}/storage/v1/object/{BUCKET}/{path}",
        headers={**_svc_headers(), "Content-Type": "image/png"},
        data=png,
        timeout=TIMEOUT,
    )
    assert upload.status_code in (200, 201), upload.text

    try:
        signed = requests.post(
            f"{KONG_URL}/storage/v1/object/sign/{BUCKET}/{path}",
            headers={**_svc_headers(), "Content-Type": "application/json"},
            json={"expiresIn": 600},
            timeout=TIMEOUT,
        )
        assert signed.status_code == 200, signed.text
        signed_path = signed.json()["signedURL"]

        # The browser hits the public gateway, not the in-docker kong hostname.
        fetched = requests.get(f"{KONG_URL}/storage/v1{signed_path}", timeout=TIMEOUT)
        assert fetched.status_code == 200
        assert fetched.content == png
    finally:
        requests.delete(
            f"{KONG_URL}/storage/v1/object/{BUCKET}/{path}",
            headers=_svc_headers(),
            timeout=TIMEOUT,
        )


def test_unsigned_screenshot_fetch_is_denied():
    res = requests.get(f"{KONG_URL}/storage/v1/object/{BUCKET}/nobody/none.png", timeout=TIMEOUT)
    assert res.status_code in (400, 401, 403, 404)


# --- backend auth chain (GoTrue JWT → FastAPI) -------------------------------------


def test_backend_rejects_request_without_token():
    res = requests.get(f"{API_URL}/api/hh/status", timeout=TIMEOUT)
    assert res.status_code in (401, 403)


def test_backend_rejects_token_signed_with_wrong_secret():
    bad = _mint_jwt(str(uuid.uuid4()), "not-the-jwt-secret")
    res = requests.get(
        f"{API_URL}/api/hh/status",
        headers={"Authorization": f"Bearer {bad}"},
        timeout=TIMEOUT,
    )
    assert res.status_code in (401, 403)


@pytest.fixture
def gotrue_user():
    """Real sign-up against the local GoTrue (autoconfirm on) — yields its access token."""
    email = f"pytest-{uuid.uuid4().hex[:12]}@example.com"
    password = f"Pw-{uuid.uuid4().hex}"
    signup = requests.post(
        f"{KONG_URL}/auth/v1/signup",
        headers={"apikey": ANON_KEY, "Content-Type": "application/json"},
        json={"email": email, "password": password},
        timeout=TIMEOUT,
    )
    assert signup.status_code == 200, signup.text
    body = signup.json()
    token = body.get("access_token")
    user_id = (body.get("user") or {}).get("id")
    assert token and user_id, f"GOTRUE_MAILER_AUTOCONFIRM must be on: {body}"

    yield {"token": token, "user_id": user_id, "email": email}

    requests.delete(
        f"{KONG_URL}/auth/v1/admin/users/{user_id}", headers=_svc_headers(), timeout=TIMEOUT
    )


def test_backend_accepts_real_gotrue_token(gotrue_user):
    """The seam that broke on the cloud→local move: frontend token → Kong → backend."""
    res = requests.get(
        f"{API_URL}/api/hh/status",
        headers={"Authorization": f"Bearer {gotrue_user['token']}"},
        timeout=TIMEOUT,
    )
    assert res.status_code == 200, res.text
    assert res.json()["connected"] is False


def test_hh_connect_validates_body_for_authed_user(gotrue_user):
    """Reaches the real hh router (no Playwright run) — 422, not the 404 Kong used to give."""
    res = requests.post(
        f"{API_URL}/api/hh/connect",
        headers={"Authorization": f"Bearer {gotrue_user['token']}"},
        json={"username": "someone@example.com", "login_method": "password"},
        timeout=TIMEOUT,
    )
    assert res.status_code == 422, res.text


def test_signup_creates_profile_row(gotrue_user):
    res = requests.get(
        f"{KONG_URL}/rest/v1/profiles?select=id&id=eq.{gotrue_user['user_id']}",
        headers=_svc_headers(),
        timeout=TIMEOUT,
    )
    assert res.status_code == 200, res.text
    assert res.json(), "sign-up trigger did not create a profiles row"


def test_backend_cors_allows_frontend_origin():
    res = requests.options(
        f"{API_URL}/api/hh/status",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
        timeout=TIMEOUT,
    )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "http://localhost:3000"
