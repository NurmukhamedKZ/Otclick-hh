"""Local self-hosted Supabase wiring — static config checks (no running stack needed).

The production frontend image must be portable between installations: per-install
Supabase JWT/anon material is supplied at container runtime, never baked into the
Next.js image. Browser traffic stays same-origin behind Caddy.
"""

import os
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


# --- local-dev template ------------------------------------------------------------


def test_frontend_dev_env_template_keeps_direct_local_ports():
    text = _read("frontend/.env.local.example")

    api_url = _env_value(text, "NEXT_PUBLIC_API_URL")
    supabase_url = _env_value(text, "NEXT_PUBLIC_SUPABASE_URL")

    assert api_url is not None and supabase_url is not None
    assert api_url.endswith(f":{BACKEND_PORT}"), f"API url must be the backend, got {api_url}"
    assert supabase_url.endswith(f":{KONG_PORT}"), f"Supabase url must be Kong, got {supabase_url}"
    assert api_url != supabase_url


# --- production frontend portability -----------------------------------------------


def test_production_frontend_does_not_bake_install_specific_supabase_values():
    compose = _read("docker-compose.yml")
    dockerfile = _read("frontend/Dockerfile")

    frontend_block = compose.split("  frontend:", 1)[1].split("\n  caddy:", 1)[0]
    assert "args:" not in frontend_block
    assert "SUPABASE_URL: http://kong:8000" in frontend_block
    assert "SUPABASE_ANON_KEY: ${ANON_KEY}" in frontend_block

    assert "ARG NEXT_PUBLIC_SUPABASE_ANON_KEY" not in dockerfile
    assert "ARG NEXT_PUBLIC_SUPABASE_URL" not in dockerfile
    assert "ARG NEXT_PUBLIC_API_URL" not in dockerfile


def test_browser_client_uses_runtime_cookie_and_same_origin():
    client = _read("frontend/src/lib/supabase/client.ts")
    api = _read("frontend/src/lib/api.ts")
    middleware = _read("frontend/src/lib/supabase/middleware.ts")

    assert 'ANON_KEY_COOKIE = "otclick-supabase-anon-key"' in client
    assert "window.location.origin" in client
    assert "NEXT_PUBLIC_SUPABASE_ANON_KEY" not in client
    assert "NEXT_PUBLIC_SUPABASE_URL" not in client
    assert "process.env.NEXT_PUBLIC_API_URL" not in api
    assert "const res = await fetch(path" in api
    assert "process.env.SUPABASE_ANON_KEY" in middleware
    assert "nextResponse.cookies.set(ANON_KEY_COOKIE" in middleware


def test_compose_keeps_api_and_kong_diagnostics_on_loopback():
    compose = _read("docker-compose.yml")

    assert f'"127.0.0.1:{KONG_PORT}:8000"' in compose
    assert f'"127.0.0.1:{BACKEND_PORT}:8000"' in compose


# --- backend env template ----------------------------------------------------------


def test_backend_env_example_uses_in_network_supabase_url():
    # Single repo-root template — backend/.env.example was folded into it.
    text = _read(".env.example")

    assert _env_value(text, "SUPABASE_URL") == "http://kong:8000"
    assert _env_value(text, "SUPABASE_PUBLIC_URL") == "http://localhost"


def test_no_cloud_supabase_leftovers_in_templates():
    for rel in (".env.example", "frontend/.env.local.example", "README.md"):
        text = _read(rel)
        assert ".supabase.co" not in text, f"{rel} still references a cloud Supabase project"


# --- prebuilt-image install/update safety -----------------------------------------


def test_fresh_db_init_runs_bind_mounted_migrations_through_shell():
    script = _read("infra/supabase/init/zz2-run-app-migrations.sh")

    assert "exec sh /migrate.sh" in script
    assert "\nexec /migrate.sh\n" not in script


def test_candidate_local_data_is_runtime_mounted_into_prebuilt_backend_services():
    compose = _read("docker-compose.yml")
    mount = "./backend/data/candidate-local:/app/data/candidate-local:ro"

    api_block = compose.split("  api:", 1)[1].split("\n  worker:", 1)[0]
    worker_block = compose.split("  worker:", 1)[1].split("\n  frontend:", 1)[0]
    assert mount in api_block
    assert mount in worker_block
