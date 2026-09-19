import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_public_installer_routes_existing_product_install_to_incremental_updater():
    installer = _read("install.sh")
    assert 'INSTALL_DIR="${OTCLICK_DIR:-/opt/otclick-hh}"' in installer
    assert 'if [[ -d "$INSTALL_DIR/.git"' in installer
    assert 'install-update.sh' in installer
    assert 'OTCLICK_FULL_INSTALL' in installer
    route_pos = installer.index('if [[ -d "$INSTALL_DIR/.git"')
    bundle_pos = installer.index('otclick-images-linux-amd64.tar.zst')
    assert route_pos < bundle_pos


def test_incremental_updater_never_downloads_combined_bundle_or_builds_locally():
    updater = _read("install-update.sh")
    assert 'OTCLICK_REF:-main' in updater
    assert 'OTCLICK_DIR:-/opt/otclick-hh' in updater
    assert 'docker-compose.prebuilt.yml' in updater
    assert 'docker pull "$image_ref"' in updater
    assert 'GHCR pull complete (cached layers reused)' in updater
    assert 'otclick-images-linux-amd64.tar.gz' not in updater
    assert 'otclick-images-linux-amd64.tar.zst' not in updater
    assert 'docker compose build' not in updater
    assert 'docker build' not in updater
    assert '--no-build' in updater


def test_repeat_update_repairs_runtime_instead_of_exiting_early():
    updater = _read("install-update.sh")
    marker = 'code already up to date: $TARGET_SHA; continuing with artifact/runtime verification'
    assert marker in updater
    marker_pos = updater.index(marker)
    reconcile_pos = updater.index('[6/7] reconciling/repairing stack without local builds')
    assert marker_pos < reconcile_pos
    block = updater[marker_pos:reconcile_pos]
    assert 'exit 0' not in block
    assert 'force-recreating frontend once' in updater
    assert 'runtime_diagnostics frontend' in updater
    assert 'require_http http://127.0.0.1:3000 frontend frontend 90' in updater


def test_cleanup_is_successful_when_no_temp_files_exist():
    updater = _read("install-update.sh")
    cleanup = updater[updater.index('cleanup() {'):updater.index('trap cleanup EXIT')]
    assert 'return 0' in cleanup
    assert '[[ -n "$MANIFEST_FILE" ]] &&' not in cleanup
    assert '[[ -n "$SUMS_FILE" ]] &&' not in cleanup


def test_incremental_updater_verifies_loaded_image_against_persisted_component_state():
    updater = _read("install-update.sh")
    assert 'image_matches_target()' in updater
    assert 'install-state.json' in updater
    assert 'backend_image_id' in updater
    assert 'frontend_image_id' in updater
    assert 'image_matches_target "$TARGET_BACKEND_HASH" "$TARGET_BACKEND_IMAGE" aiautoclicker-backend:latest backend || BACKEND_CHANGED=1' in updater
    assert 'image_matches_target "$TARGET_FRONTEND_HASH" "$TARGET_FRONTEND_IMAGE" aiautoclicker-frontend:latest frontend || FRONTEND_CHANGED=1' in updater


def test_incremental_updater_accepts_existing_exact_digest_during_state_v1_upgrade():
    updater = _read("install-update.sh")
    assert 'docker image inspect "$target_ref"' in updater
    assert 'target_id="$(docker image inspect "$target_ref"' in updater
    assert '[[ -n "$target_id" && "$target_id" == "$local_id" ]]' in updater


def test_incremental_updater_preserves_env():
    updater = _read("install-update.sh")
    assert '[[ -f "$INSTALL_DIR/.env" ]]' in updater
    assert 'restore the original .env before updating' in updater
    assert 'infra/bootstrap.py' not in updater


def test_incremental_updater_is_release_first_with_configurable_transport():
    updater = _read("install-update.sh")
    env_example = _read(".env.example")
    assert 'OTCLICK_IMAGE_TRANSPORT:-$(env_get OTCLICK_IMAGE_TRANSPORT)' in updater
    assert 'requested="${requested:-release}"' in updater
    assert 'auto)' in updater
    assert 'release|ghcr)' in updater
    assert 'component Release unavailable; falling back to GHCR' in updater
    assert 'GHCR unavailable; falling back to component Release' in updater
    assert 'OTCLICK_IMAGE_TRANSPORT=release' in env_example


def test_artifact_workflow_is_content_addressed_and_tests_public_ghcr():
    workflow = _read(".github/workflows/build-artifact.yml")
    assert 'packages: write' in workflow
    assert 'BACKEND_HASH' in workflow
    assert 'FRONTEND_HASH' in workflow
    assert 'ghcr.io/${owner}/otclick-hh-backend:component-${BACKEND_HASH}' in workflow
    assert 'ghcr.io/${owner}/otclick-hh-frontend:component-${FRONTEND_HASH}' in workflow
    assert 'Verify anonymous GHCR pulls' in workflow
    assert 'docker logout ghcr.io' in workflow
    assert 'docker pull "$BACKEND_IMAGE"' in workflow
    assert 'docker pull "$FRONTEND_IMAGE"' in workflow
    assert '"schema_version": 2' in workflow
    assert '"fresh_install_bundle": "otclick-images-linux-amd64.tar.zst"' in workflow


def test_product_frontend_keeps_standalone_same_origin_runtime_contract():
    override = _read("docker-compose.prebuilt.yml")
    dockerfile = _read("frontend/Dockerfile")
    client = _read("frontend/src/lib/supabase/client.ts")

    assert 'services: {}' in override
    assert 'entrypoint:' not in override
    assert 'frontend-runtime-env.sh' not in override
    assert 'CMD ["node", "server.js"]' in dockerfile
    assert 'window.location.origin' in client
    assert 'otclick-supabase-anon-key' in client


def test_exact_release_checksum_contract_matches_fresh_and_incremental_clients():
    workflow = _read(".github/workflows/build-artifact.yml")
    fresh = _read("install.sh")
    updater = _read("install-update.sh")

    assert 'otclick-images-linux-amd64.tar.zst' in workflow
    assert '"fresh_install_bundle": "otclick-images-linux-amd64.tar.zst"' in workflow
    assert 'expected_digest=' in fresh
    assert 'actual_digest=' in fresh
    assert 'release bundle SHA-256 mismatch' in fresh
    assert 'expected_manifest=' in updater


def test_incremental_updater_exposes_native_pull_progress():
    updater = _read("install-update.sh")
    assert "exec 3>&1" in updater
    assert '[[ -t 3 ]]' in updater
    assert "image_transfer_size" in updater
    assert "Docker layer progress shows downloaded / total and updates in place" in updater
    assert "script -qefc" in updater
    assert "curl shows total, received, speed and ETA" in updater
    assert 'docker_pull_visible "$name" "$image_ref"' in updater


def test_curl_pipe_cannot_leak_remaining_installer_source_into_pull_tty():
    installer = _read("install.sh")
    updater = _read("install-update.sh")
    assert 'bash "$tmp_update" </dev/null' in installer
    assert "exec </dev/null" in updater
    assert "script -qefc" in updater
    assert '"$transcript" </dev/null' in updater
    assert 'docker pull "$image_ref" </dev/null' in updater


def test_backend_health_checks_use_health_endpoint():
    updater = _read("install-update.sh")
    assert "wait_http http://127.0.0.1:8000/health backend 45" in updater
    assert "require_http http://127.0.0.1:8000/health backend api 90" in updater
    assert "wait_http http://127.0.0.1:8000 backend 45" not in updater
    assert "require_http http://127.0.0.1:8000 backend api 90" not in updater


def test_production_proxy_contract_uses_loopback_service_ports_and_caddy():
    compose = _read("docker-compose.yml")
    caddy = _read("infra/Caddyfile")
    env_example = _read(".env.example")

    assert compose.count("\n  caddy:\n") == 1
    assert '"127.0.0.1:3000:3000"' in compose
    assert '"127.0.0.1:8000:8000"' in compose
    assert '"127.0.0.1:54321:8000"' in compose
    assert 'container_name: aiautoclicker-caddy' in compose
    assert './infra/Caddyfile:/etc/caddy/Caddyfile:ro' in compose
    assert 'reverse_proxy frontend:3000' in caddy
    assert 'reverse_proxy api:8000' in caddy
    assert 'reverse_proxy kong:8000' in caddy
    assert 'OTCLICK_PROXY_MODE=auto' in env_example
    assert 'CADDY_HTTP_BIND=80' in env_example
    assert 'CADDY_HTTPS_BIND=443' in env_example


def test_installers_restore_and_reconcile_caddy_without_normal_local_app_builds():
    fresh = _read("install.sh")
    updater = _read("install-update.sh")

    for script in (fresh, updater):
        assert 'configure_proxy_mode()' in script
        assert 'foreign_public_proxy()' in script

    assert 'OTCLICK_ALLOW_LOCAL_BUILD' in fresh
    assert 'load_prebuilt_app_images' in fresh
    assert 'docker compose pull db migrate auth rest realtime storage storage-init kong caddy' in fresh
    assert 'wait_http "http://127.0.0.1:${OTCLICK_INTERNAL_HTTP_PORT:-18080}/health" internal-Caddy 60' in fresh

    assert 'caddy_health_url()' in updater
    assert 'repaired stale empty infra/Caddyfile directory' in updater
    assert 'compose pull db migrate auth rest realtime storage storage-init kong caddy' in updater
    assert 'require_http "$CADDY_HEALTH_URL" internal-Caddy caddy 60' in updater
    assert 'docker compose build' not in updater
    assert 'docker build' not in updater


def test_repeat_update_repairs_missing_caddy_image():
    updater = _read("install-update.sh")
    assert "docker image inspect caddy:2-alpine" in updater
    assert "compose pull caddy" in updater
    assert "compose unchanged but Caddy image is missing; pulling Caddy only" in updater


def test_unified_product_surface_keeps_vacancy_funnel_and_removes_billing():
    assert (ROOT / "frontend/src/app/(app)/vacancies/page.tsx").is_file()
    assert (ROOT / "frontend/src/app/(app)/vacancies/run/page.tsx").is_file()
    assert (ROOT / "frontend/src/app/(app)/vacancies/rules/page.tsx").is_file()
    assert (ROOT / "frontend/src/app/(app)/vacancies/cover-letter-editor.tsx").is_file()
    assert not (ROOT / "frontend/src/app/(app)/billing/page.tsx").exists()


def test_cover_letter_prompt_migration_follows_product_pipeline_migrations():
    migrations = ROOT / "infra/supabase/migrations"
    for number in range(35, 43):
        assert list(migrations.glob(f"{number:03d}_*.sql")), f"missing product migration {number:03d}"
    assert not (migrations / "035_cover_letter_prompt_version.sql").exists()
    assert (migrations / "043_cover_letter_prompt_version.sql").is_file()


def test_install_state_v2_writer_reader_round_trip(tmp_path):
    """Prove the reader and writer heredocs extracted from install-update.sh
    actually behave correctly.  No docker, no network, no shell execution."""
    updater = _read("install-update.sh")

    # --- extract the PYSTATE reader heredoc ---
    pystate_start_marker = "<<'PYSTATE'"
    if pystate_start_marker not in updater:
        raise AssertionError("PYSTATE heredoc start marker not found in install-update.sh")
    search_from = updater.index(pystate_start_marker) + len(pystate_start_marker)
    pystate_end = updater.index("\nPYSTATE\n", search_from)
    reader_code = updater[search_from:pystate_end].lstrip("\n")

    # --- extract the last <<'PY' … PY heredoc (the state writer) ---
    last_py_marker = "<<'PY'"
    last_py_pos = updater.rfind(last_py_marker)
    if last_py_pos == -1:
        raise AssertionError("<<'PY'> heredoc marker not found in install-update.sh")
    py_start = last_py_pos + len(last_py_marker)
    # find the matching closing PY on its own line
    py_end = updater.index("\nPY\n", py_start)
    writer_code = updater[py_start:py_end].lstrip("\n")

    reader_path = tmp_path / "reader.py"
    writer_path = tmp_path / "writer.py"
    reader_path.write_text(reader_code, encoding="utf-8")
    writer_path.write_text(writer_code, encoding="utf-8")

    state_file = tmp_path / "install-state.json"

    # --- write a v2 state via the extracted writer ---
    git_sha = "abc123"
    backend_hash = "bh1"
    frontend_hash = "fh1"
    compose_hash = "ch1"
    infra_hash = "ih1"
    migrations_hash = "mh1"
    backend_image_id = "sha256:aaaa"
    frontend_image_id = "sha256:bbbb"

    result = subprocess.run(
        [
            sys.executable,
            str(writer_path),
            str(state_file),
            git_sha,
            backend_hash,
            frontend_hash,
            compose_hash,
            infra_hash,
            migrations_hash,
            backend_image_id,
            frontend_image_id,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"writer failed: {result.stderr}"

    # --- (d) writer output must be valid v2 JSON with all expected keys ---
    assert state_file.exists()
    mode = state_file.stat().st_mode & 0o777
    assert mode == 0o600, f"expected mode 0o600, got {oct(mode)}"
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert data["backend_image_id"] == backend_image_id
    assert data["frontend_image_id"] == frontend_image_id
    assert data["backend_hash"] == backend_hash
    assert data["frontend_hash"] == frontend_hash
    assert data["compose_hash"] == compose_hash
    assert data["infra_hash"] == infra_hash
    assert data["migrations_hash"] == migrations_hash
    assert data["git_sha"] == git_sha
    assert "updated_at" in data

    # --- (a) reader: matching hash + matching image_id → exit 0 ---
    result = subprocess.run(
        [sys.executable, str(reader_path),
         str(state_file), "backend", backend_hash, backend_image_id],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"reader should succeed: {result.stderr}"

    # --- (b) reader: hash mismatch → non-zero exit ---
    result = subprocess.run(
        [sys.executable, str(reader_path),
         str(state_file), "backend", "WRONG_HASH", backend_image_id],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "reader should fail on hash mismatch"

    # --- (c) reader: image_id mismatch → non-zero exit ---
    result = subprocess.run(
        [sys.executable, str(reader_path),
         str(state_file), "backend", backend_hash, "sha256:WRONG"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "reader should fail on image_id mismatch"
