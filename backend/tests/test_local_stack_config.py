"""Local self-hosted Supabase wiring — static config checks (no running stack needed).

Guards the class of bug that broke hh auth after the cloud→local move: the frontend
was built with NEXT_PUBLIC_API_URL pointing at Kong (54321) instead of the backend
(8000), so every /api/* call 404'd. NEXT_PUBLIC_* is baked at image build time, so a
wrong default in a template file silently ships.
"""

import os
import re
from pathlib import Path

# Set required env BEFORE importing app modules
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault(
    "FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc="
)

REPO_ROOT = Path(__file__).resolve().parents[2]

KONG_PORT = "54321"
BACKEND_PORT = "8000"


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text()


def _env_value(text: str, key: str) -> str | None:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return None


# --- browser-reachable signed URLs -------------------------------------------------


def test_browser_reachable_rewrites_internal_host(monkeypatch):
    from app.config import settings
    from app.services.hh_auth import _browser_reachable

    monkeypatch.setattr(settings, "SUPABASE_URL", "http://kong:8000")
    monkeypatch.setattr(settings, "SUPABASE_PUBLIC_URL", "http://localhost:54321")

    signed = "http://kong:8000/storage/v1/object/sign/captcha-screenshots/u/1.png?token=x"
    assert _browser_reachable(signed) == (
        "http://localhost:54321/storage/v1/object/sign/captcha-screenshots/u/1.png?token=x"
    )


def test_browser_reachable_tolerates_trailing_slashes(monkeypatch):
    from app.config import settings
    from app.services.hh_auth import _browser_reachable

    monkeypatch.setattr(settings, "SUPABASE_URL", "http://kong:8000/")
    monkeypatch.setattr(settings, "SUPABASE_PUBLIC_URL", "http://localhost:54321/")

    assert _browser_reachable("http://kong:8000/storage/v1/x.png") == (
        "http://localhost:54321/storage/v1/x.png"
    )


def test_browser_reachable_leaves_foreign_hosts_alone(monkeypatch):
    from app.config import settings
    from app.services.hh_auth import _browser_reachable

    monkeypatch.setattr(settings, "SUPABASE_URL", "http://kong:8000")
    monkeypatch.setattr(settings, "SUPABASE_PUBLIC_URL", "http://localhost:54321")

    other = "https://img.hh.ru/captcha/abc.png"
    assert _browser_reachable(other) == other


def test_browser_reachable_noop_when_public_url_empty(monkeypatch):
    from app.config import settings
    from app.services.hh_auth import _browser_reachable

    monkeypatch.setattr(settings, "SUPABASE_URL", "http://kong:8000")
    monkeypatch.setattr(settings, "SUPABASE_PUBLIC_URL", "")

    signed = "http://kong:8000/storage/v1/x.png"
    assert _browser_reachable(signed) == signed


def test_supabase_public_url_has_local_default():
    from app.config import Settings

    assert Settings.model_fields["SUPABASE_PUBLIC_URL"].default == "http://localhost:54321"


# --- port wiring: backend is 8000, Kong is 54321 -----------------------------------


def test_frontend_env_template_points_api_at_backend_not_kong():
    text = _read("frontend/.env.local.example")

    api_url = _env_value(text, "NEXT_PUBLIC_API_URL")
    supabase_url = _env_value(text, "NEXT_PUBLIC_SUPABASE_URL")

    assert api_url is not None and supabase_url is not None
    assert api_url.endswith(f":{BACKEND_PORT}"), f"API url must be the backend, got {api_url}"
    assert supabase_url.endswith(f":{KONG_PORT}"), f"Supabase url must be Kong, got {supabase_url}"
    assert api_url != supabase_url


def test_compose_api_url_default_points_at_backend():
    compose = _read("docker-compose.yml")

    match = re.search(r"NEXT_PUBLIC_API_URL:\s*\$\{NEXT_PUBLIC_API_URL:-([^}]+)\}", compose)
    assert match, "compose must define a NEXT_PUBLIC_API_URL build arg with a default"
    assert match.group(1).strip().endswith(f":{BACKEND_PORT}")


def test_compose_publishes_both_ports():
    compose = _read("docker-compose.yml")

    assert f'"{KONG_PORT}:8000"' in compose, "Kong must be published on 54321"
    assert f'"{BACKEND_PORT}:8000"' in compose, "backend must be published on 8000"


# --- backend env template ----------------------------------------------------------


def test_backend_env_example_uses_in_network_supabase_url():
    # Single repo-root template — backend/.env.example was folded into it.
    text = _read(".env.example")

    assert _env_value(text, "SUPABASE_URL") == "http://kong:8000"
    assert _env_value(text, "SUPABASE_PUBLIC_URL") == f"http://localhost:{KONG_PORT}"


def test_no_cloud_supabase_leftovers_in_templates():
    for rel in (".env.example", "frontend/.env.local.example", "README.md"):
        text = _read(rel)
        assert ".supabase.co" not in text, f"{rel} still references a cloud Supabase project"
