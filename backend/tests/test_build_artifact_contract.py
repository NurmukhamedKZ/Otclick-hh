from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _workflow() -> str:
    return (ROOT / ".github/workflows/build-artifact.yml").read_text(encoding="utf-8")


def test_linux_artifact_publishes_content_addressed_components():
    workflow = _workflow()

    assert "packages: write" in workflow
    assert "BACKEND_HASH" in workflow
    assert "FRONTEND_HASH" in workflow
    assert "ghcr.io/${owner}/otclick-hh-backend:component-${BACKEND_HASH}" in workflow
    assert "ghcr.io/${owner}/otclick-hh-frontend:component-${FRONTEND_HASH}" in workflow
    assert 'docker manifest inspect "$BACKEND_TAG"' in workflow
    assert 'docker manifest inspect "$FRONTEND_TAG"' in workflow
    assert 'docker image inspect "$BACKEND_TAG"' in workflow
    assert 'docker image inspect "$FRONTEND_TAG"' in workflow


def test_linux_artifact_has_per_component_fallbacks_for_incremental_updates():
    workflow = _workflow()

    assert "otclick-backend-linux-amd64.tar.zst" in workflow
    assert "otclick-frontend-linux-amd64.tar.zst" in workflow
    assert "component-backend-${BACKEND_HASH}" in workflow
    assert "component-frontend-${FRONTEND_HASH}" in workflow
    assert 'docker save "$image"' in workflow
    assert "Fallback already exists" in workflow


def test_combined_bundle_is_retained_only_for_fresh_install_compatibility():
    workflow = _workflow()

    assert "Package fresh-install compatibility bundle" in workflow
    assert "fresh-install/otclick-images-linux-amd64.tar.zst" in workflow
    assert "incremental updater does not download this" in workflow
    assert '"fresh_install_bundle": "otclick-images-linux-amd64.tar.zst"' in workflow


def test_exact_commit_release_contains_v2_manifest_and_metadata():
    workflow = _workflow()

    assert 'tag="install-${GITHUB_SHA}"' in workflow
    assert '"schema_version": 2' in workflow
    assert '"components": {' in workflow
    assert '"hashes": {' in workflow
    assert "artifacts/manifest.json" in workflow
    assert "artifacts/SHA256SUMS" in workflow
    assert "artifacts/install-update.sh" in workflow
    assert "artifacts/docker-compose.prebuilt.yml" in workflow
    assert "Verify published exact-SHA metadata" in workflow
    assert 'https://github.com/${GITHUB_REPOSITORY}/releases/tag/install-${GITHUB_SHA}' in workflow


def test_linux_artifact_uses_short_retention_metadata_upload():
    workflow = _workflow()

    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in workflow
    assert "name: otclick-linux-amd64-${{ github.sha }}" in workflow
    assert "retention-days: 7" in workflow
    assert "compression-level: 0" in workflow
    assert "if-no-files-found: error" in workflow


def test_linux_artifact_never_publishes_runtime_secrets():
    workflow = _workflow()

    assert "cp install.sh install-one.sh install-update.sh docker-compose.yml docker-compose.prebuilt.yml artifacts/" in workflow
    assert "cp .env" not in workflow
    assert "OPENAI_API_KEY" not in workflow
    assert "SERVICE_ROLE_KEY" not in workflow
    assert "FERNET_KEY" not in workflow


def test_component_builds_use_persistent_buildx_cache():
    workflow = _workflow()
    assert '"perf/**"' in workflow
    assert "docker/setup-buildx-action@" in workflow
    assert "docker/build-push-action@" in workflow
    assert "cache-from: type=gha,scope=backend" in workflow
    assert "cache-to: type=gha,mode=max,scope=backend" in workflow
    assert "cache-from: type=gha,scope=frontend" in workflow
    assert "cache-to: type=gha,mode=max,scope=frontend" in workflow
