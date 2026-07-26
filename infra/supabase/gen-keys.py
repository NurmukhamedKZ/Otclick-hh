#!/usr/bin/env python3
"""Generate a JWT_SECRET + matching ANON_KEY/SERVICE_ROLE_KEY for a local
self-hosted Supabase stack. Stdlib only — no PyJWT dependency.

Usage: python3 infra/supabase/gen-keys.py
Paste the three printed lines into backend/.env (and the two NEXT_PUBLIC_
lines into your root .env for the frontend build).
"""

import base64
import hashlib
import hmac
import json
import secrets
import time


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_jwt(secret: str, role: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "role": role,
        "iss": "supabase-local",
        "iat": now,
        # ~10 years — self-hosted, rotate by re-running this script.
        "exp": now + 10 * 365 * 24 * 3600,
    }
    signing_input = f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}." \
        f"{_b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def main() -> None:
    jwt_secret = secrets.token_urlsafe(32)
    anon_key = make_jwt(jwt_secret, "anon")
    service_role_key = make_jwt(jwt_secret, "service_role")
    print(f"JWT_SECRET={jwt_secret}")
    print(f"ANON_KEY={anon_key}")
    print(f"SERVICE_ROLE_KEY={service_role_key}")


if __name__ == "__main__":
    main()
