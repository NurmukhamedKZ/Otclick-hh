from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _installer() -> str:
    return (ROOT / "install.sh").read_text(encoding="utf-8")


def _shim() -> str:
    return (ROOT / "install-one.sh").read_text(encoding="utf-8")


def _updater() -> str:
    return (ROOT / "install-update.sh").read_text(encoding="utf-8")


def test_one_command_installer_preserves_existing_docker_stack():
    installer = _installer()

    assert 'docker compose version >/dev/null 2>&1' in installer
    assert 'existing Docker + Compose detected; package stack left untouched' in installer
    assert 'apt-get install -y git curl ca-certificates python3 zstd >>"$LOG_FILE" 2>&1' in installer


def test_one_command_installer_keeps_docker_package_families_separate():
    installer = _installer()

    assert 'docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin' in installer
    assert 'apt-get install -y docker.io docker-compose-v2' in installer
    assert 'Docker CE/containerd.io detected; installing matching Compose plugin' in installer
    assert 'Ubuntu docker.io detected; installing matching Compose v2 package' in installer


def test_one_command_installer_hides_noisy_package_and_docker_progress():
    installer = _installer()

    assert 'apt-get update >>"$LOG_FILE" 2>&1' in installer
    assert 'docker compose pull db migrate auth rest realtime storage storage-init kong caddy >>"$LOG_FILE" 2>&1' in installer
    assert 'docker compose build api frontend >>"$LOG_FILE" 2>&1' in installer
    assert 'details -> $LOG_FILE' in installer
    assert 'trap - ERR' in installer


def test_one_command_installer_prints_compose_failure_diagnostics_without_tailing_its_own_log():
    installer = _installer()

    assert 'diagnose_stack() {' in installer
    assert 'compose_or_diagnose() {' in installer
    assert 'docker compose ps -a >&2' in installer
    assert 'docker compose logs --no-color --tail=120 "$service" >&2' in installer
    assert "state_error=\"$(docker inspect -f '{{.State.Error}}'" in installer
    assert 'error=${state_error:-none}' in installer
    assert 'docker compose command failed:' in installer
    assert 'tail -n 30 "$LOG_FILE"' not in installer


def test_full_installer_keeps_exact_sha_legacy_bundle_fallback():
    installer = _installer()

    assert 'git_sha="$(git rev-parse HEAD)"' in installer
    assert 'release_tag="install-${git_sha}"' in installer
    assert 'https://github.com/gest0r1/Otclick-hh/releases/download/${release_tag}' in installer
    assert '"${release_base}/manifest.json"' in installer
    assert '"${release_base}/SHA256SUMS"' in installer
    assert 'manifest.get("git_sha", "")' in installer
    assert 'sha256sum "$bundle_file"' in installer
    assert 'zstd -d -c "$bundle_file" | docker load' in installer


def test_one_command_installer_does_not_build_locally_unless_explicitly_overridden():
    installer = _installer()

    assert 'OTCLICK_ALLOW_LOCAL_BUILD:-0' in installer
    assert '[7/8] emergency local build enabled' in installer
    assert 'Local build is intentionally disabled on low-memory hosts.' in installer
    assert 'Emergency override: OTCLICK_ALLOW_LOCAL_BUILD=1' in installer
    assert '[7/8] downloading prebuilt Otclick images (~1 GiB, no local build)' in installer


def test_one_command_installer_never_pulls_local_backend_as_external_image():
    installer = _installer()

    assert 'docker compose pull db migrate auth rest realtime storage storage-init kong caddy' in installer
    assert 'docker compose pull api' not in installer
    assert 'docker compose pull worker' not in installer


def test_installer_starts_infra_then_forces_only_current_app_images():
    installer = _installer()

    assert 'compose_or_diagnose up -d --no-build --pull never \\\n    db migrate auth rest realtime storage storage-init kong' in installer
    assert '--force-recreate --no-deps api frontend' in installer
    assert '--force-recreate --no-deps worker' in installer
    assert '--force-recreate --no-deps worker caddy' not in installer
    assert 'compose_or_diagnose up -d --no-build --pull never --no-deps caddy' in installer
    assert 'Caddy contains no application code' in installer
    assert 'Keep an already-running proxy stable' in installer
    assert 'Docker Compose does not reliably recreate an existing container' in installer
    assert 'without bouncing DB' in installer


def test_candidate_overrides_stay_private_but_readable_by_container_user():
    installer = _installer()

    assert 'chown 1000:1000 "$CANDIDATE_LOCAL_DIR"' in installer
    assert 'chmod 700 "$CANDIDATE_LOCAL_DIR"' in installer
    assert 'chmod 600 "$CANDIDATE_LOCAL_DIR/candidate_profile.json"' in installer
    assert 'backend/Dockerfile runs the API/worker as uid:gid 1000:1000' in installer


def test_candidate_reload_uses_runtime_mount_without_building_images():
    installer = _installer()

    assert "docker compose exec -T api python scripts/load_candidate_data.py" in installer
    assert "docker compose up -d --build api worker && docker compose exec" not in installer


def test_one_command_shim_uses_incremental_updater_for_existing_install():
    shim = _shim()

    assert 'RAW_URL="https://raw.githubusercontent.com/gest0r1/Otclick-hh/${REF}/install.sh"' in shim
    assert '[[ -d "$INSTALL_DIR/.git"' in shim
    assert 'install-update.sh' in shim
    assert 'OTCLICK_FULL_INSTALL:-0' in shim
    assert 'exec env OTCLICK_REF="$REF" OTCLICK_DIR="$INSTALL_DIR" bash "$TMP_INSTALL" "$@"' in shim
    assert 'replace_once(' not in shim


def test_incremental_updater_downloads_only_changed_or_missing_exact_components():
    updater = _updater()

    assert 'OLD_BACKEND_HASH="$(component_hash backend)"' in updater
    assert 'OLD_FRONTEND_HASH="$(component_hash frontend)"' in updater
    assert 'backend exact image already present; 0 application bytes downloaded' in updater
    assert 'frontend exact image already present; 0 application bytes downloaded' in updater
    assert 'image_matches_target "$TARGET_BACKEND_IMAGE" aiautoclicker-backend:latest || BACKEND_CHANGED=1' in updater
    assert 'image_matches_target "$TARGET_FRONTEND_IMAGE" aiautoclicker-frontend:latest || FRONTEND_CHANGED=1' in updater
    assert 'if [[ "$BACKEND_CHANGED" == "1" ]]' in updater
    assert 'if [[ "$FRONTEND_CHANGED" == "1" ]]' in updater


def test_incremental_updater_prefers_immutable_ghcr_layers_with_component_fallback():
    updater = _updater()

    assert 'docker pull "$image_ref"' in updater
    assert 'GHCR pull complete (cached layers reused)' in updater
    assert 'anonymous GHCR pull unavailable; using component Release fallback' in updater
    assert 'releases/download/${fallback_tag}' in updater
    assert 'zstd -d -c "$fallback_file" | docker load' in updater
    assert 'sha256sum "$fallback_file"' in updater


def test_incremental_updater_skips_unneeded_backup_and_third_party_pull_but_repairs_runtime():
    updater = _updater()

    assert 'schema unchanged; DB backup skipped' in updater
    assert 'compose unchanged; third-party image pull skipped' in updater
    assert 'if [[ "$MIGRATIONS_CHANGED" == "1" ]]' in updater
    assert 'if [[ "$COMPOSE_CHANGED" == "1" ]]' in updater
    assert 'creating DB backup before schema migration' in updater
    assert '[6/7] reconciling/repairing stack without local builds' in updater
    assert 'compose up -d --no-build --pull never db migrate' in updater


def test_incremental_updater_recreates_changed_app_services_and_keeps_caddy_separate():
    updater = _updater()

    assert 'compose up -d --no-build --pull never --force-recreate api worker' in updater
    assert 'compose up -d --no-build --pull never --force-recreate frontend' in updater
    assert 'compose up -d --no-build --pull never --force-recreate --no-deps caddy' in updater
    assert 'compose up -d --no-build --pull never --no-deps caddy' in updater
    assert 'ALLOW_REAL_APPLY=true' not in updater


def test_installer_repairs_known_obsolete_local_wrapper_change_but_not_other_files():
    installer = _installer()

    assert 'git status --porcelain --untracked-files=no -- install-one.sh' in installer
    assert 'restoring obsolete local install-one.sh changes' in installer
    assert 'git restore --source=HEAD --staged --worktree -- install-one.sh' in installer
    assert 'tracked local changes that block update:' in installer


def test_installer_auto_switches_to_external_proxy_when_80_443_are_owned_elsewhere():
    installer = _installer()

    assert "foreign_public_proxy()" in installer
    assert "OTCLICK_PROXY_MODE external" in installer
    assert 'CADDY_HTTP_BIND "127.0.0.1:${OTCLICK_INTERNAL_HTTP_PORT:-18080}"' in installer
    assert 'CADDY_HTTPS_BIND "127.0.0.1:${OTCLICK_INTERNAL_HTTPS_PORT:-18443}"' in installer
    assert 'env_set CADDY_SITE_ADDRESS ":80"' in installer
    assert "external reverse proxy detected on host 80/443" in installer
    assert "external proxy action required" in installer


def test_installer_cleans_only_superseded_otclick_app_images():
    installer = _installer()

    assert 'remove_previous_app_image() {' in installer
    assert 'docker image rm "$old_id"' in installer
    assert 'remove_previous_app_image "$old_backend_image" "$current_backend_image" backend' in installer
    assert 'remove_previous_app_image "$old_frontend_image" "$current_frontend_image" frontend' in installer
    executable_lines = [
        line.strip()
        for line in installer.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert not any(line.startswith("docker image prune -a") for line in executable_lines)


def test_compose_caddy_host_bindings_are_runtime_configurable():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert '${CADDY_HTTP_BIND:-80}:80' in compose
    assert '${CADDY_HTTPS_BIND:-443}:443' in compose
