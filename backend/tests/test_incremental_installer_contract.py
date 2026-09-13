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


def test_incremental_updater_requires_exact_target_digest_not_just_latest_tag():
    updater = _read("install-update.sh")
    assert 'image_matches_target()' in updater
    assert 'docker image inspect "$target_ref"' in updater
    assert 'docker image inspect "$local_tag"' in updater
    assert 'target_id=' in updater
    assert 'local_id=' in updater
    assert 'image_matches_target "$TARGET_BACKEND_IMAGE" aiautoclicker-backend:latest || BACKEND_CHANGED=1' in updater
    assert 'image_matches_target "$TARGET_FRONTEND_IMAGE" aiautoclicker-frontend:latest || FRONTEND_CHANGED=1' in updater


def test_incremental_updater_preserves_env():
    updater = _read("install-update.sh")
    assert '[[ -f "$INSTALL_DIR/.env" ]]' in updater
    assert 'restore the original .env before updating' in updater
    assert 'infra/bootstrap.py' not in updater


def test_incremental_updater_uses_release_fallback_only_after_ghcr_failure():
    updater = _read("install-update.sh")
    ghcr = updater.index('docker pull "$image_ref"')
    fallback = updater.index('using component Release fallback')
    zstd = updater.index('ensure_zstd')
    assert ghcr < fallback
    assert zstd < fallback
    assert 'command -v zstd' in updater


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

    assert 'OTCLICK_ALLOW_LOCAL_BUILD' in fresh  # explicit emergency override only
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
