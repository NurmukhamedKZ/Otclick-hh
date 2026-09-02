"""Shim config: reads the repo-root .env (same one the backend reads)."""
import os
import sys
from pathlib import Path

# Make sure repo-root .env is loaded before anything imports this.
ROOT = Path(__file__).resolve().parent.parent
_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_env, override=False)

PGHOST = os.environ.get("SHIM_PGHOST", "127.0.0.1")
PGPORT = int(os.environ.get("SHIM_PGPORT", "5433"))
PGUSER = os.environ.get("SHIM_PGUSER", "postgres")
PGPASSWORD = os.environ.get("POSTGRES_PASSWORD", "")
PGDATABASE = os.environ.get("SHIM_PGDATABASE", "postgres")

JWT_SECRET = os.environ["JWT_SECRET"]
ANON_KEY = os.environ["ANON_KEY"]
SERVICE_ROLE_KEY = os.environ["SERVICE_ROLE_KEY"]

# Storage root on disk for the captcha-screenshots bucket.
STORAGE_ROOT = ROOT / ".shim-storage"

# How long (seconds) an issued access token lives. GoTrue default is 3600.
ACCESS_TOKEN_TTL = int(os.environ.get("SHIM_JWT_TTL", "3600"))
