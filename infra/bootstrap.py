#!/usr/bin/env python3
"""Write a ready-to-run repo-root .env: generate every secret and paste it into
all the slots that have to agree. Stdlib only — runs before `uv sync`.

Usage: python3 infra/bootstrap.py [--force]
"""

import argparse
import base64
import importlib.util
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_make_jwt():
    """gen-keys.py has a dash in its name — import it by path."""
    path = ROOT / "infra" / "supabase" / "gen-keys.py"
    spec = importlib.util.spec_from_file_location("gen_keys", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.make_jwt


def generate() -> dict[str, str]:
    make_jwt = _load_make_jwt()
    jwt_secret = secrets.token_urlsafe(32)
    anon = make_jwt(jwt_secret, "anon")
    service = make_jwt(jwt_secret, "service_role")
    return {
        "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
        "JWT_SECRET": jwt_secret,
        "ANON_KEY": anon,
        "SERVICE_ROLE_KEY": service,
        "SUPABASE_ANON_KEY": anon,
        "SUPABASE_SERVICE_ROLE_KEY": service,
        "NEXT_PUBLIC_SUPABASE_ANON_KEY": anon,
        # Same as Fernet.generate_key(), without importing cryptography.
        "FERNET_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "INTERNAL_CRON_TOKEN": secrets.token_urlsafe(32),
    }


def render(template: str, values: dict[str, str]) -> str:
    """Replace `KEY=` lines in .env.example with the generated values."""
    seen = set()
    out = []
    for line in template.splitlines():
        match = re.match(r"([A-Z0-9_]+)=", line)
        key = match.group(1) if match else None
        if key in values:
            seen.add(key)
            out.append(f"{key}={values[key]}")
        else:
            out.append(line)
    missing = set(values) - seen
    if missing:
        raise SystemExit(f".env.example has no slot for: {', '.join(sorted(missing))}")
    return "\n".join(out) + "\n"


def ask_openai_key() -> str:
    """The one value we cannot generate. Skipped on a non-interactive stdin."""
    if not sys.stdin.isatty():
        return ""
    print("OpenAI/OpenAI-compatible key — powers vacancy scoring and candidate-facing AI text.")
    print("Enter to skip; discovery/review still work and AI failures stay explicit.")
    return input("OPENAI_API_KEY: ").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite an existing .env")
    parser.add_argument("--openai-key", default=None, help="skip the prompt and use this key")
    args = parser.parse_args()

    target = ROOT / ".env"
    if target.exists() and not args.force:
        sys.exit(f"{target} already exists — delete it or pass --force (this rotates every secret).")

    values = generate()
    openai_key = args.openai_key if args.openai_key is not None else ask_openai_key()
    if openai_key:
        values["OPENAI_API_KEY"] = openai_key

    target.write_text(render((ROOT / ".env.example").read_text(), values))
    target.chmod(0o600)
    print(f"\nWrote {target}.")
    if not openai_key:
        print("No AI key: search/discovery/manual review can run, but LLM scoring and")
        print("new-funnel cover-letter generation will report an explicit unavailable/error state.")
        print("Add OPENAI_API_KEY later or point OPENAI_BASE_URL at a compatible model.")


if __name__ == "__main__":
    main()
