#!/usr/bin/env bash
set -Eeuo pipefail

# Incremental production updater for an existing Otclick installation.
# It downloads only a tiny exact-SHA manifest, then downloads only changed
# application components. GitHub Release component archives are the production
# default because some hosting networks route GHCR blob traffic very slowly; GHCR
# remains an immutable fallback/override. The combined fresh-install bundle is
# never downloaded by this script.
#
# Important: an already-up-to-date checkout still runs the runtime reconciliation
# path. This makes the same one-command installer usable as a repair command after
# an interrupted deployment or a stopped/crashed application container.

REPO_SLUG="${OTCLICK_REPO_SLUG:-NurmukhamedKZ/Otclick-hh}"
REF="${OTCLICK_REF:-main}"
INSTALL_DIR="${OTCLICK_DIR:-/opt/otclick-hh}"
LOG_DIR="${OTCLICK_LOG_DIR:-/var/log/otclick-hh}"
STATE_DIR="${OTCLICK_STATE_DIR:-/var/lib/otclick-hh}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$LOG_DIR/update-$STAMP.log"
MANIFEST_FILE=""
SUMS_FILE=""
BACKUP_FILE=""

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (use sudo)." >&2
  exit 1
fi

# The updater is deliberately non-interactive. When install.sh itself is run as
# `curl ... | bash`, stdin may still contain unread bytes from install.sh after
# the exec handoff. Disconnect stdin before any child process can consume and
# echo that source text into the terminal.
exec </dev/null

mkdir -p "$LOG_DIR" "$STATE_DIR"
chmod 700 "$LOG_DIR" "$STATE_DIR"
touch "$LOG_FILE"
chmod 600 "$LOG_FILE"

# Preserve the caller's real terminal before stdout/stderr are redirected to tee.
# Docker sees a TTY on fd 3 and therefore renders its native layer progress
# in-place instead of emitting one new line for every progress update.
INTERACTIVE_TERMINAL=0
exec 3>&1
if [[ -t 3 ]]; then
  INTERACTIVE_TERMINAL=1
fi
exec > >(tee -a "$LOG_FILE") 2>&1

log() { printf '[otclick] %s\n' "$*"; }
die() { printf '[otclick] ERROR: %s\n' "$*" >&2; exit 1; }

on_error() {
  local code=$?
  trap - ERR
  echo
  echo "[otclick] incremental update failed (exit $code)."
  if [[ -n "$BACKUP_FILE" ]]; then
    echo "Database backup: $BACKUP_FILE"
  fi
  echo "Log: $LOG_FILE"
  exit "$code"
}
trap on_error ERR

# EXIT traps must always return 0. The previous form used `[[ ... ]] && rm ...`;
# with empty temp-file variables the last test returned 1 and incorrectly fired
# the ERR trap even after a successful `exit 0` on an up-to-date checkout.
cleanup() {
  if [[ -n "$MANIFEST_FILE" ]]; then
    rm -f "$MANIFEST_FILE" || true
  fi
  if [[ -n "$SUMS_FILE" ]]; then
    rm -f "$SUMS_FILE" || true
  fi
  return 0
}
trap cleanup EXIT

for tool in git curl python3 sha256sum docker; do
  command -v "$tool" >/dev/null 2>&1 || die "required tool is missing: $tool"
done
docker compose version >/dev/null 2>&1 || die "docker compose v2 is required"
[[ -d "$INSTALL_DIR/.git" ]] || die "existing installation not found at $INSTALL_DIR; use install.sh for a fresh install"
[[ -f "$INSTALL_DIR/.env" ]] || die "$INSTALL_DIR/.env is missing; restore the original .env before updating"

cd "$INSTALL_DIR"

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  log "tracked local changes that block update:"
  git status --short --untracked-files=no | sed 's/^/[otclick]   /'
  die "commit/stash tracked changes before update"
fi

compose() {
  docker compose -f docker-compose.yml -f docker-compose.prebuilt.yml "$@"
}

env_get() {
  local key="$1"
  [[ -f .env ]] || return 0
  sed -n "s/^${key}=//p" .env | tail -n 1
}

env_set() {
  local key="$1" value="$2"
  python3 - .env "$key" "$value" <<'PYENV'
from pathlib import Path
import sys
path = Path(sys.argv[1])
key, value = sys.argv[2], sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines()
prefix = key + "="
out = []
replaced = False
for line in lines:
    if line.startswith(prefix):
        if not replaced:
            out.append(prefix + value)
            replaced = True
        continue
    out.append(line)
if not replaced:
    out.append(prefix + value)
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PYENV
  chmod 600 .env
}

foreign_public_proxy() {
  docker ps --format '{{.Names}}\t{{.Ports}}' 2>/dev/null \
    | grep -Ev '^aiautoclicker-caddy[[:space:]]' \
    | grep -Eq '(^|,|[[:space:]])(0\.0\.0\.0:|\[::\]:)?(80|443)->'
}

configure_proxy_mode() {
  local explicit_mode mode
  explicit_mode="${OTCLICK_PROXY_MODE:-}"
  mode="${explicit_mode:-$(env_get OTCLICK_PROXY_MODE)}"

  if [[ -z "$mode" || "$mode" == "auto" ]]; then
    if foreign_public_proxy; then
      mode="external"
    else
      mode="direct"
    fi
  fi

  case "$mode" in
    direct)
      env_set OTCLICK_PROXY_MODE direct
      env_set CADDY_HTTP_BIND "80"
      env_set CADDY_HTTPS_BIND "443"
      log "      proxy mode: direct Caddy on host 80/443"
      ;;
    external)
      env_set OTCLICK_PROXY_MODE external
      env_set CADDY_HTTP_BIND "127.0.0.1:${OTCLICK_INTERNAL_HTTP_PORT:-18080}"
      env_set CADDY_HTTPS_BIND "127.0.0.1:${OTCLICK_INTERNAL_HTTPS_PORT:-18443}"
      env_set CADDY_SITE_ADDRESS ":80"
      log "      proxy mode: external reverse proxy; Caddy on loopback ${OTCLICK_INTERNAL_HTTP_PORT:-18080}/${OTCLICK_INTERNAL_HTTPS_PORT:-18443}"
      ;;
    *)
      die "invalid OTCLICK_PROXY_MODE=$mode (expected auto/direct/external)"
      ;;
  esac
}

caddy_health_url() {
  local bind port
  bind="$(env_get CADDY_HTTP_BIND)"
  bind="${bind:-80}"
  port="${bind##*:}"
  printf 'http://127.0.0.1:%s/health' "$port"
}

component_hash() {
  local component="$1"
  python3 - "$component" <<'PY'
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys

component = sys.argv[1]
pathspecs = {
    "backend": [
        ".dockerignore",
        "backend/Dockerfile",
        "backend/app",
        "backend/worker_main.py",
        "backend/data",
        "backend/scripts",
        "pyproject.toml",
        "uv.lock",
    ],
    "frontend": ["frontend"],
    "compose": ["docker-compose.yml", "docker-compose.prebuilt.yml"],
    "infra": ["infra"],
    "migrations": ["infra/supabase/migrations"],
}
if component not in pathspecs:
    raise SystemExit(f"unknown component: {component}")
raw = subprocess.check_output(["git", "ls-files", "-z", "--", *pathspecs[component]])
files = sorted({p.decode("utf-8") for p in raw.split(b"\0") if p})
h = hashlib.sha256()
for rel in files:
    path = Path(rel)
    if not path.is_file():
        continue
    h.update(rel.encode("utf-8"))
    h.update(b"\0")
    h.update(path.read_bytes())
    h.update(b"\0")
print(h.hexdigest())
PY
}

wait_http() {
  local url="$1" label="$2" timeout="${3:-90}" i
  for ((i=1; i<=timeout; i++)); do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      log "      $label healthy"
      return 0
    fi
    sleep 1
  done
  return 1
}

runtime_diagnostics() {
  local service="$1"
  echo >&2
  echo "[otclick] runtime diagnostics for $service:" >&2
  compose ps -a >&2 || true
  echo >&2
  compose logs --no-color --tail=200 "$service" >&2 || true
}

require_http() {
  local url="$1" label="$2" service="$3" timeout="${4:-90}"
  if wait_http "$url" "$label" "$timeout"; then
    return 0
  fi
  runtime_diagnostics "$service"
  die "$label did not become healthy: $url"
}

wait_migrate() {
  local id state exit_code i
  for ((i=1; i<=90; i++)); do
    id="$(compose ps -aq migrate 2>/dev/null | head -n1)"
    if [[ -n "$id" ]]; then
      state="$(docker inspect -f '{{.State.Status}}' "$id" 2>/dev/null || true)"
      if [[ "$state" == "exited" ]]; then
        exit_code="$(docker inspect -f '{{.State.ExitCode}}' "$id" 2>/dev/null || true)"
        if [[ "$exit_code" == "0" ]]; then
          log "      migrations complete"
          return 0
        fi
        runtime_diagnostics migrate
        die "database migrations failed (exit ${exit_code:-unknown})"
      fi
    fi
    sleep 2
  done
  runtime_diagnostics migrate
  die "database migrations did not finish"
}

backup_database() {
  mkdir -p backups
  chmod 700 backups
  local db_id db_health i tmp
  db_id="$(compose ps -q db 2>/dev/null || true)"
  if [[ -z "$db_id" || "$(docker inspect -f '{{.State.Running}}' "$db_id" 2>/dev/null || true)" != "true" ]]; then
    log "      starting DB for migration backup"
    compose up -d --no-build --pull never db >>"$LOG_FILE" 2>&1
    for ((i=1; i<=60; i++)); do
      db_id="$(compose ps -q db 2>/dev/null || true)"
      db_health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$db_id" 2>/dev/null || true)"
      [[ "$db_health" == "healthy" || "$db_health" == "running" ]] && break
      sleep 2
    done
  fi
  [[ -n "$db_id" ]] || die "database container unavailable for backup"
  BACKUP_FILE="$INSTALL_DIR/backups/postgres-$STAMP.dump"
  tmp="$BACKUP_FILE.tmp"
  log "      creating DB backup before schema migration"
  rm -f "$tmp"
  compose exec -T db pg_dump -U postgres -d postgres -Fc >"$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$BACKUP_FILE"
}

ensure_zstd() {
  command -v zstd >/dev/null 2>&1 && return 0
  if command -v apt-get >/dev/null 2>&1; then
    log "      installing zstd for component Release transport"
    apt-get update -qq >>"$LOG_FILE" 2>&1
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq zstd >>"$LOG_FILE" 2>&1
  fi
  command -v zstd >/dev/null 2>&1 || die "zstd is required for the GitHub Release component transport, but could not be installed"
}

image_matches_target() {
  local target_hash="$1" target_ref="$2" local_tag="$3" component="$4" local_id target_id
  docker image inspect "$local_tag" >/dev/null 2>&1 || return 1
  local_id="$(docker image inspect "$local_tag" --format '{{.Id}}')"

  # Preferred v2 state: works for both Release-loaded and GHCR-pulled images.
  if [[ -f "$STATE_DIR/install-state.json" ]] && python3 - "$STATE_DIR/install-state.json" "$component" "$target_hash" "$local_id" <<'PYSTATE'
import json
import sys

path, component, target_hash, local_id = sys.argv[1:]
try:
    data = json.load(open(path, encoding="utf-8"))
except Exception:
    raise SystemExit(1)
if data.get(f"{component}_hash") != target_hash:
    raise SystemExit(1)
if data.get(f"{component}_image_id") != local_id:
    raise SystemExit(1)
PYSTATE
  then
    return 0
  fi

  # One-time compatibility with schema-v1 state: if an earlier GHCR-first
  # updater already pulled the exact digest, trust the content-addressed ref and
  # avoid redownloading the component merely to upgrade install-state metadata.
  docker image inspect "$target_ref" >/dev/null 2>&1 || return 1
  target_id="$(docker image inspect "$target_ref" --format '{{.Id}}')"
  [[ -n "$target_id" && "$target_id" == "$local_id" ]]
}


image_transfer_size() {
  local image_ref="$1"
  docker manifest inspect "$image_ref" 2>/dev/null | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
total = sum(int(layer.get("size") or 0) for layer in data.get("layers", []))
if total <= 0:
    raise SystemExit(1)
n = float(total)
units = ("B", "KiB", "MiB", "GiB", "TiB")
for unit in units:
    if n < 1024 or unit == units[-1]:
        print(f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}")
        break
    n /= 1024
'
}

append_pull_transcript() {
  local transcript="$1"
  [[ -s "$transcript" ]] || return 0
  python3 - "$transcript" "$LOG_FILE" <<'PYLOG'
from pathlib import Path
import re
import sys

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
ansi = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
text = src.read_bytes().decode("utf-8", "replace")
text = ansi.sub("", text).replace("\r", "\n")
with dst.open("a", encoding="utf-8") as out:
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("Script started on ") or line.startswith("Script done on "):
            continue
        out.write(line + "\n")
PYLOG
}

docker_pull_visible() {
  local name="$1" image_ref="$2" transcript rc

  if [[ "$INTERACTIVE_TERMINAL" != "1" ]]; then
    docker pull "$image_ref" </dev/null >>"$LOG_FILE" 2>&1
    return $?
  fi

  printf '[otclick]       %s: Docker layer progress shows downloaded / total and updates in place\n' "$name" >&3

  if command -v script >/dev/null 2>&1; then
    transcript="$(mktemp /tmp/otclick-docker-pull.XXXXXX.log)"
    rc=0
    OTCLICK_PULL_IMAGE="$image_ref" script -qefc 'docker pull "$OTCLICK_PULL_IMAGE"' "$transcript" </dev/null >&3 2>&3 || rc=$?
    append_pull_transcript "$transcript" || true
    rm -f "$transcript"
    return "$rc"
  fi

  # util-linux `script` is expected on supported Ubuntu hosts. If it is absent,
  # still send Docker directly to the original terminal so native progress stays
  # visible, at the cost of not mirroring the detailed pull transcript to the log.
  docker pull "$image_ref" </dev/null >&3 2>&3
}

curl_download_visible() {
  local label="$1" url="$2" output="$3"
  if [[ "$INTERACTIVE_TERMINAL" == "1" ]]; then
    printf '[otclick]       %s: downloading (curl shows total, received, speed and ETA)\n' "$label" >&3
    curl -fL --retry 3 --retry-delay 2 --retry-all-errors --show-error \
      "$url" -o "$output" 2>&3
  else
    curl -fL --retry 3 --retry-delay 2 --retry-all-errors \
      "$url" -o "$output" >>"$LOG_FILE" 2>&1
  fi
}

OLD_SHA="$(git rev-parse HEAD)"
OLD_BACKEND_HASH="$(component_hash backend)"
OLD_FRONTEND_HASH="$(component_hash frontend)"
OLD_COMPOSE_HASH="$(component_hash compose)"
OLD_INFRA_HASH="$(component_hash infra)"
OLD_MIGRATIONS_HASH="$(component_hash migrations)"

log "[1/7] checking repository head"
git fetch --prune origin "$REF" >>"$LOG_FILE" 2>&1
TARGET_SHA="$(git rev-parse "origin/$REF")"
if [[ "$TARGET_SHA" == "$OLD_SHA" && "${OTCLICK_FORCE_UPDATE:-0}" != "1" ]]; then
  log "      code already up to date: $TARGET_SHA; continuing with artifact/runtime verification"
fi

log "[2/7] fetching exact-SHA incremental manifest"
release_tag="install-${TARGET_SHA}"
release_base="https://github.com/${REPO_SLUG}/releases/download/${release_tag}"
MANIFEST_FILE="$(mktemp /tmp/otclick-manifest.XXXXXX.json)"
SUMS_FILE="$(mktemp /tmp/otclick-sums.XXXXXX)"

ready=0
for attempt in $(seq 1 36); do
  if curl -fsSL --retry 2 --retry-delay 1 "${release_base}/manifest.json" -o "$MANIFEST_FILE" \
     && curl -fsSL --retry 2 --retry-delay 1 "${release_base}/SHA256SUMS" -o "$SUMS_FILE"; then
    ready=1
    break
  fi
  [[ "$attempt" -eq 36 ]] && break
  [[ $((attempt % 6)) -eq 0 ]] && log "      artifact is still being built in GitHub Actions..."
  sleep 10
done
[[ "$ready" == "1" ]] || die "prebuilt manifest is not ready for ${TARGET_SHA}"

expected_manifest="$(awk '$2 == "manifest.json" || $2 == "./manifest.json" {print $1; exit}' "$SUMS_FILE")"
[[ -n "$expected_manifest" ]] || die "manifest checksum is missing"
actual_manifest="$(sha256sum "$MANIFEST_FILE" | awk '{print $1}')"
[[ "$actual_manifest" == "$expected_manifest" ]] || die "manifest checksum mismatch"

mapfile -t META < <(python3 - "$MANIFEST_FILE" "$TARGET_SHA" <<'PY'
import json
import sys

path, target_sha = sys.argv[1:]
data = json.load(open(path, encoding="utf-8"))
if data.get("schema_version") != 2:
    raise SystemExit("unsupported manifest schema")
if data.get("git_sha") != target_sha:
    raise SystemExit("manifest git_sha mismatch")
if data.get("architecture") != "linux/amd64":
    raise SystemExit("unsupported manifest architecture")
components = data["components"]
hashes = data["hashes"]
for key in ("backend", "frontend"):
    comp = components[key]
    for field in ("hash", "image", "fallback_tag", "fallback_asset"):
        if not comp.get(field):
            raise SystemExit(f"manifest missing {key}.{field}")
print(components["backend"]["hash"])
print(components["backend"]["image"])
print(components["backend"]["fallback_tag"])
print(components["backend"]["fallback_asset"])
print(components["frontend"]["hash"])
print(components["frontend"]["image"])
print(components["frontend"]["fallback_tag"])
print(components["frontend"]["fallback_asset"])
print(hashes["compose"])
print(hashes["infra"])
print(hashes["migrations"])
PY
)
[[ "${#META[@]}" -eq 11 ]] || die "invalid manifest metadata"

TARGET_BACKEND_HASH="${META[0]}"
TARGET_BACKEND_IMAGE="${META[1]}"
TARGET_BACKEND_FALLBACK_TAG="${META[2]}"
TARGET_BACKEND_FALLBACK_ASSET="${META[3]}"
TARGET_FRONTEND_HASH="${META[4]}"
TARGET_FRONTEND_IMAGE="${META[5]}"
TARGET_FRONTEND_FALLBACK_TAG="${META[6]}"
TARGET_FRONTEND_FALLBACK_ASSET="${META[7]}"
TARGET_COMPOSE_HASH="${META[8]}"
TARGET_INFRA_HASH="${META[9]}"
TARGET_MIGRATIONS_HASH="${META[10]}"

BACKEND_CHANGED=0
FRONTEND_CHANGED=0
COMPOSE_CHANGED=0
INFRA_CHANGED=0
MIGRATIONS_CHANGED=0
[[ "$OLD_BACKEND_HASH" != "$TARGET_BACKEND_HASH" ]] && BACKEND_CHANGED=1
[[ "$OLD_FRONTEND_HASH" != "$TARGET_FRONTEND_HASH" ]] && FRONTEND_CHANGED=1
[[ "$OLD_COMPOSE_HASH" != "$TARGET_COMPOSE_HASH" ]] && COMPOSE_CHANGED=1
[[ "$OLD_INFRA_HASH" != "$TARGET_INFRA_HASH" ]] && INFRA_CHANGED=1
[[ "$OLD_MIGRATIONS_HASH" != "$TARGET_MIGRATIONS_HASH" ]] && MIGRATIONS_CHANGED=1

# Do not trust a pre-existing :latest tag merely because the source hash did not
# change. The interrupted migration from the old installer can leave an older
# locally-built image under the same tag. Require the exact target digest.
image_matches_target "$TARGET_BACKEND_HASH" "$TARGET_BACKEND_IMAGE" aiautoclicker-backend:latest backend || BACKEND_CHANGED=1
image_matches_target "$TARGET_FRONTEND_HASH" "$TARGET_FRONTEND_IMAGE" aiautoclicker-frontend:latest frontend || FRONTEND_CHANGED=1

log "      changed/required: backend=$BACKEND_CHANGED frontend=$FRONTEND_CHANGED compose=$COMPOSE_CHANGED infra=$INFRA_CHANGED migrations=$MIGRATIONS_CHANGED"

pull_component_from_release() {
  local name="$1" fallback_tag="$2" fallback_asset="$3" local_tag="$4"
  local fallback_base fallback_sums fallback_file expected actual

  ensure_zstd
  fallback_base="https://github.com/${REPO_SLUG}/releases/download/${fallback_tag}"
  fallback_sums="$(mktemp /tmp/otclick-component-sums.XXXXXX)"
  fallback_file="$(mktemp /tmp/otclick-component.XXXXXX.tar.zst)"
  curl -fsSL --retry 3 --retry-delay 2 "${fallback_base}/SHA256SUMS" -o "$fallback_sums" \
    || { rm -f "$fallback_sums" "$fallback_file"; return 21; }
  expected="$(awk -v asset="$fallback_asset" '$2 == asset || $2 == "./" asset {print $1; exit}' "$fallback_sums")"
  [[ -n "$expected" ]] || { rm -f "$fallback_sums" "$fallback_file"; return 22; }
  curl_download_visible "$name component Release" \
    "${fallback_base}/${fallback_asset}" "$fallback_file" || { rm -f "$fallback_sums" "$fallback_file"; return 23; }
  actual="$(sha256sum "$fallback_file" | awk '{print $1}')"
  [[ "$actual" == "$expected" ]] || { rm -f "$fallback_sums" "$fallback_file"; return 24; }
  zstd -d -c "$fallback_file" | docker load >>"$LOG_FILE" 2>&1 || { rm -f "$fallback_sums" "$fallback_file"; return 25; }
  rm -f "$fallback_sums" "$fallback_file"
  docker image inspect "$local_tag" >/dev/null 2>&1 || return 26
  log "      $name: component Release loaded"
}

pull_component_from_ghcr() {
  local name="$1" image_ref="$2" local_tag="$3" transfer_size
  transfer_size="$(image_transfer_size "$image_ref" || true)"
  if [[ -n "$transfer_size" ]]; then
    log "      $name: pulling immutable image from GHCR (compressed image up to $transfer_size; cached layers are reused)"
  else
    log "      $name: pulling immutable image from GHCR"
  fi
  docker_pull_visible "$name" "$image_ref" || return $?
  docker tag "$image_ref" "$local_tag"
  log "      $name: GHCR pull complete (cached layers reused)"
}

pull_component() {
  local name="$1" image_ref="$2" fallback_tag="$3" fallback_asset="$4" local_tag="$5"
  local requested transport
  requested="${OTCLICK_IMAGE_TRANSPORT:-$(env_get OTCLICK_IMAGE_TRANSPORT)}"
  requested="${requested:-release}"
  case "$requested" in
    auto)
      # Release-first is intentionally the current auto policy. It preserves the
      # fast GitHub Release CDN path observed on production hosting while GHCR
      # remains a content-addressed fallback.
      transport="release"
      ;;
    release|ghcr)
      transport="$requested"
      ;;
    *)
      die "invalid OTCLICK_IMAGE_TRANSPORT=$requested (expected auto/release/ghcr)"
      ;;
  esac

  log "      $name: image transport=$requested (effective=$transport)"
  if [[ "$transport" == "release" ]]; then
    if pull_component_from_release "$name" "$fallback_tag" "$fallback_asset" "$local_tag"; then
      return 0
    fi
    log "      $name: component Release unavailable; falling back to GHCR"
    pull_component_from_ghcr "$name" "$image_ref" "$local_tag"
    return $?
  fi

  if pull_component_from_ghcr "$name" "$image_ref" "$local_tag"; then
    return 0
  fi
  log "      $name: GHCR unavailable; falling back to component Release"
  pull_component_from_release "$name" "$fallback_tag" "$fallback_asset" "$local_tag"
}

log "[3/7] updating changed application components"
if [[ "$BACKEND_CHANGED" == "1" ]]; then
  pull_component backend "$TARGET_BACKEND_IMAGE" "$TARGET_BACKEND_FALLBACK_TAG" "$TARGET_BACKEND_FALLBACK_ASSET" "aiautoclicker-backend:latest"
else
  log "      backend exact image already present; 0 application bytes downloaded"
fi
if [[ "$FRONTEND_CHANGED" == "1" ]]; then
  pull_component frontend "$TARGET_FRONTEND_IMAGE" "$TARGET_FRONTEND_FALLBACK_TAG" "$TARGET_FRONTEND_FALLBACK_ASSET" "aiautoclicker-frontend:latest"
else
  log "      frontend exact image already present; 0 application bytes downloaded"
fi

log "[4/7] fast-forwarding repository"
# A broken previous deployment can leave infra/Caddyfile as an empty directory
# after the tracked file disappeared from main. Remove only that exact empty
# directory so Git can restore the tracked Caddyfile; never delete its contents.
if [[ -d infra/Caddyfile ]]; then
  if rmdir infra/Caddyfile 2>/dev/null; then
    log "      repaired stale empty infra/Caddyfile directory"
  else
    die "infra/Caddyfile is a non-empty directory; move it aside manually before updating"
  fi
fi
git checkout "$REF" >>"$LOG_FILE" 2>&1
git merge --ff-only "origin/$REF" >>"$LOG_FILE" 2>&1
[[ "$(git rev-parse HEAD)" == "$TARGET_SHA" ]] || die "repository did not reach target revision"
[[ -f docker-compose.prebuilt.yml ]] || die "docker-compose.prebuilt.yml is missing after update"
[[ -f infra/frontend-runtime-env.sh ]] || die "frontend runtime env injector is missing after update"
[[ -f infra/Caddyfile ]] || die "infra/Caddyfile is missing after update"
configure_proxy_mode

if [[ "$MIGRATIONS_CHANGED" == "1" ]]; then
  log "[5/7] schema changed; backing up PostgreSQL"
  backup_database
else
  log "[5/7] schema unchanged; DB backup skipped"
fi

if [[ "$COMPOSE_CHANGED" == "1" ]]; then
  log "      compose changed; refreshing pinned third-party images"
  compose pull db migrate auth rest realtime storage storage-init kong caddy >>"$LOG_FILE" 2>&1
elif ! docker image inspect caddy:2-alpine >/dev/null 2>&1; then
  log "      compose unchanged but Caddy image is missing; pulling Caddy only"
  compose pull caddy >>"$LOG_FILE" 2>&1
else
  log "      compose unchanged; third-party image pull skipped"
fi

log "[6/7] reconciling/repairing stack without local builds"
# Always run the idempotent migration job and reconcile every runtime service.
# This is deliberate even when git is already current: a repeated installer run
# doubles as a safe repair after an interrupted deployment.
compose up -d --no-build --pull never db migrate >>"$LOG_FILE" 2>&1
wait_migrate
compose up -d --no-build --pull never db auth rest realtime storage storage-init kong >>"$LOG_FILE" 2>&1
require_http http://127.0.0.1:54321/auth/v1/health Supabase-auth auth 90

if [[ "$BACKEND_CHANGED" == "1" || "$COMPOSE_CHANGED" == "1" || "$INFRA_CHANGED" == "1" ]]; then
  compose up -d --no-build --pull never --force-recreate api worker >>"$LOG_FILE" 2>&1
else
  compose up -d --no-build --pull never api worker >>"$LOG_FILE" 2>&1
fi
if ! wait_http http://127.0.0.1:8000/health backend 45; then
  log "      backend health failed; force-recreating api/worker once"
  runtime_diagnostics api
  compose up -d --no-build --pull never --force-recreate api worker >>"$LOG_FILE" 2>&1
  require_http http://127.0.0.1:8000/health backend api 90
fi

if [[ "$FRONTEND_CHANGED" == "1" || "$COMPOSE_CHANGED" == "1" || "$INFRA_CHANGED" == "1" ]]; then
  compose up -d --no-build --pull never --force-recreate frontend >>"$LOG_FILE" 2>&1
else
  compose up -d --no-build --pull never frontend >>"$LOG_FILE" 2>&1
fi
if ! wait_http http://127.0.0.1:3000 frontend 45; then
  log "      frontend health failed; force-recreating frontend once"
  runtime_diagnostics frontend
  compose up -d --no-build --pull never --force-recreate frontend >>"$LOG_FILE" 2>&1
  require_http http://127.0.0.1:3000 frontend frontend 90
fi

CADDY_HEALTH_URL="$(caddy_health_url)"
if [[ "$COMPOSE_CHANGED" == "1" || "$INFRA_CHANGED" == "1" ]]; then
  compose up -d --no-build --pull never --force-recreate --no-deps caddy >>"$LOG_FILE" 2>&1
else
  compose up -d --no-build --pull never --no-deps caddy >>"$LOG_FILE" 2>&1
fi
require_http "$CADDY_HEALTH_URL" internal-Caddy caddy 60

BACKEND_IMAGE_ID="$(docker image inspect aiautoclicker-backend:latest --format '{{.Id}}')"
FRONTEND_IMAGE_ID="$(docker image inspect aiautoclicker-frontend:latest --format '{{.Id}}')"
python3 - "$STATE_DIR/install-state.json" "$TARGET_SHA" "$TARGET_BACKEND_HASH" "$TARGET_FRONTEND_HASH" "$TARGET_COMPOSE_HASH" "$TARGET_INFRA_HASH" "$TARGET_MIGRATIONS_HASH" "$BACKEND_IMAGE_ID" "$FRONTEND_IMAGE_ID" <<'PY'
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

path = Path(sys.argv[1])
state = {
    "schema_version": 2,
    "git_sha": sys.argv[2],
    "backend_hash": sys.argv[3],
    "frontend_hash": sys.argv[4],
    "compose_hash": sys.argv[5],
    "infra_hash": sys.argv[6],
    "migrations_hash": sys.argv[7],
    "backend_image_id": sys.argv[8],
    "frontend_image_id": sys.argv[9],
    "updated_at": datetime.now(timezone.utc).isoformat(),
}
path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
path.chmod(0o600)
PY

log "[7/7] update/repair complete"
log "      revision: $TARGET_SHA"
log "      application components pulled: backend=$BACKEND_CHANGED frontend=$FRONTEND_CHANGED"
if [[ -n "$BACKUP_FILE" ]]; then
  log "      DB backup: $BACKUP_FILE"
fi
log "      frontend: http://127.0.0.1:3000 healthy"
log "      backend: http://127.0.0.1:8000/health healthy"
log "      caddy: $CADDY_HEALTH_URL healthy"
log "      log: $LOG_FILE"
