"""Make the recon scripts runnable from the host.

The app's SUPABASE_URL is the in-network compose hostname (http://kong:8000),
which does not resolve outside docker — a script run from a shell dies on a DNS
error deep inside httpx. Point it at the browser-reachable URL instead. Env vars
outrank the .env file in pydantic-settings, so this must run BEFORE any app
import.
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV = Path(__file__).resolve().parent.parent.parent / ".env"


def use_public_supabase_url() -> None:
    if "kong" not in os.environ.get("SUPABASE_URL", "kong"):
        return  # already host-reachable
    public = "http://localhost:54321"
    if _ENV.exists():
        for line in _ENV.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "SUPABASE_PUBLIC_URL" and value.strip():
                public = value.split("#")[0].strip()
                break
    os.environ["SUPABASE_URL"] = public
