#!/usr/bin/env bash
set -Eeuo pipefail

# Backward-compatible one-command entry point. Fresh installs use the canonical
# install.sh bootstrap; existing installs use the incremental updater so normal
# application changes do not redownload the full image bundle.
REF="${OTCLICK_REF:-feature/persistent-vacancy-funnel}"
INSTALL_DIR="${OTCLICK_DIR:-/opt/otclick-hh}"
RAW_URL="https://raw.githubusercontent.com/gest0r1/Otclick-hh/${REF}/install.sh"
if [[ -d "$INSTALL_DIR/.git" && "${OTCLICK_FULL_INSTALL:-0}" != "1" ]]; then
  RAW_URL="https://raw.githubusercontent.com/gest0r1/Otclick-hh/${REF}/install-update.sh"
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (use sudo)." >&2
  exit 1
fi

TMP_INSTALL="$(mktemp /tmp/otclick-install.XXXXXX.sh)"
trap 'rm -f "$TMP_INSTALL"' EXIT
curl -fsSL "$RAW_URL" -o "$TMP_INSTALL"
chmod 700 "$TMP_INSTALL"
exec env OTCLICK_REF="$REF" OTCLICK_DIR="$INSTALL_DIR" bash "$TMP_INSTALL" "$@"
