from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_env_defaults_keep_signup_and_real_apply_closed():
    env = _read(".env.example")

    assert "DISABLE_SIGNUP=true" in env
    assert "ALLOW_REAL_APPLY=false" in env
    assert "OTCLICK_USER_ID=" in env
    assert "CADDY_SITE_ADDRESS=:80" in env


def test_env_supports_generic_openai_compatible_provider():
    env = _read(".env.example")

    assert "OPENAI_BASE_URL=" in env
    assert "OPENAI_MODEL=" in env
    assert "OPENAI_STRUCTURED_OUTPUT_METHOD=function_calling" in env
    assert "https://opencode.ai/zen/go/v1" in env
    assert "longcat-2.0" in env


def test_compose_keeps_application_services_local_and_caddy_runtime_bindable():
    compose = _read("docker-compose.yml")

    assert 'GOTRUE_DISABLE_SIGNUP: "${DISABLE_SIGNUP:-true}"' in compose
    assert '"127.0.0.1:54321:8000"' in compose
    assert '"127.0.0.1:8000:8000"' in compose
    assert '"127.0.0.1:3000:3000"' in compose
    assert '"${CADDY_HTTP_BIND:-80}:80"' in compose
    assert '"${CADDY_HTTPS_BIND:-443}:443"' in compose
    assert '"${CADDY_HTTPS_BIND:-443}:443/udp"' in compose


def test_caddy_keeps_browser_on_one_origin():
    caddy = _read("infra/Caddyfile")

    assert "reverse_proxy api:8000" in caddy
    assert "reverse_proxy kong:8000" in caddy
    assert "reverse_proxy frontend:3000" in caddy
    assert "/api/*" in caddy
    assert "/auth/*" in caddy
    assert "/rest/*" in caddy
    assert "/storage/*" in caddy


def test_next_proxy_is_registered_next_to_src_app():
    src_proxy = ROOT / "frontend/src/proxy.ts"
    root_proxy = ROOT / "frontend/proxy.ts"

    assert src_proxy.is_file()
    assert not root_proxy.exists()
    proxy = src_proxy.read_text(encoding="utf-8")
    assert 'updateSession(request)' in proxy
    assert 'export async function proxy' in proxy
    assert 'matcher:' in proxy


def test_backend_image_contains_prepared_candidate_loader():
    dockerfile = _read("backend/Dockerfile")
    dockerignore = _read(".dockerignore")

    assert "COPY backend/data ./data" in dockerfile
    assert "COPY backend/scripts ./scripts" in dockerfile
    assert "\nbackend/scripts\n" not in dockerignore


def test_update_backs_up_before_fetch_and_preserves_env_secrets():
    installer = _read("install.sh")

    backup_pos = installer.index("backup_existing")
    fetch_pos = installer.index('git fetch --prune origin')
    assert backup_pos < fetch_pos
    assert "infra/bootstrap.py --force" not in installer
    assert "preserving existing .env" in installer
    assert "pg_dump -U postgres -d postgres -Fc" in installer
    assert 'reconfigure="${OTCLICK_RECONFIGURE:-0}"' in installer
    assert "Normal update: preserve the current origin" in installer


def test_installer_creates_one_user_via_admin_and_loads_candidate_context():
    installer = _read("install.sh")

    assert "GOTRUE" not in installer  # auth configuration stays in compose, not shell mutation
    assert "auth/v1/admin/users" in installer
    assert 'env_set DISABLE_SIGNUP true' in installer
    assert "scripts/load_candidate_data.py" in installer
    assert "--data-dir data/candidate-local" in installer
    assert "multiple profiles exist" in installer


def test_installer_never_enables_real_apply():
    installer = _read("install.sh")

    assert "ALLOW_REAL_APPLY=true" not in installer
    assert "Real HH submit: DISABLED by default" in installer


def test_fresh_installer_prompts_through_tty_and_configures_llm():
    installer = _read("install.sh")

    # /dev/tty keeps prompts usable when the script itself was downloaded by curl.
    assert "</dev/tty" in installer
    assert "OpenCode Go + LongCat 2.0" in installer
    assert "https://opencode.ai/zen/go/v1" in installer
    assert 'model="longcat-2.0"' in installer
    assert "LongCat direct OpenAI-compatible API" in installer
    assert "https://api.longcat.chat/openai/v1" in installer
    assert "Custom OpenAI-compatible endpoint" in installer
    assert "API key выбранного LLM provider" in installer
    assert "infra/verify_llm.py --env .env" in installer
    assert "OPENAI_STRUCTURED_OUTPUT_METHOD function_calling" in installer


def test_installer_prompts_for_app_identity_and_public_url():
    installer = _read("install.sh")

    assert "URL приложения (https://domain или LAN http://IP)" in installer
    assert "Email для входа в Otclick" in installer
    assert "Пароль Otclick (Enter = сгенерировать безопасный)" in installer
    assert "Повтори пароль Otclick" in installer


def test_installer_uses_git_ignored_local_candidate_files():
    installer = _read("install.sh")
    gitignore = _read(".gitignore")

    assert "backend/data/candidate-local/" in gitignore
    assert 'CANDIDATE_LOCAL_DIR="$INSTALL_DIR/backend/data/candidate-local"' in installer
    assert 'cp "$source_dir/candidate_profile.json" "$CANDIDATE_LOCAL_DIR/candidate_profile.json"' in installer
    assert 'cp "$source_dir/confirmed_facts.json" "$CANDIDATE_LOCAL_DIR/confirmed_facts.json"' in installer


def test_installer_prints_candidate_completion_files_and_reload_command():
    installer = _read("install.sh")

    assert "$CANDIDATE_LOCAL_DIR/candidate_profile.json" in installer
    assert "$CANDIDATE_LOCAL_DIR/confirmed_facts.json" in installer
    assert "Candidate profile:" in installer
    assert "no mandatory manual completion" in installer
    assert "ACTION REQUIRED" in installer
    assert "These files are ignored by Git" in installer
    assert "docker compose exec -T api python scripts/load_candidate_data.py" in installer
    assert "--data-dir data/candidate-local" in installer


def test_llm_verifier_requires_function_calling():
    verifier = _read("infra/verify_llm.py")

    assert '"tools"' in verifier
    assert '"tool_choice"' in verifier
    assert '"emit_check"' in verifier
    assert 'base + "/chat/completions"' in verifier
