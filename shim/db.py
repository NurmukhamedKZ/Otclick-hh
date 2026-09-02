"""Postgres connection + JWT helpers for the shim.

We connect as the superuser `postgres` (bypasses RLS), which is exactly what
the service_role client does in the real Supabase stack. The anon client only
needs auth.get_user (JWT validation), which we handle directly from the JWT
without hitting the DB.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg2
from psycopg2.extras import RealDictCursor

from . import config


def db() -> Any:
    """Open a new psycopg2 connection. Callers close it (use db_ctx)."""
    return psycopg2.connect(
        host=config.PGHOST,
        port=config.PGPORT,
        user=config.PGUSER,
        password=config.PGPASSWORD,
        dbname=config.PGDATABASE,
        cursor_factory=RealDictCursor,
    )


@contextmanager
def db_ctx() -> Iterator[Any]:
    conn = db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def make_jwt(user_id: str, email: str, role: str = "authenticated") -> str:
    """Issue a GoTrue-compatible HS256 JWT for a user.

    GoTrue JWT payload fields the backend/frontend rely on:
      sub (user uuid), aud, role, email, exp, iat, iss, session_id, is_anonymous.
    """
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "sub": user_id,
        "aud": "authenticated",
        "role": role,
        "email": email,
        "iss": "supabase-local",
        "iat": now,
        "exp": now + config.ACCESS_TOKEN_TTL,
        "session_id": _b64url(hashlib.sha1(f"{user_id}{now}".encode()).digest())[:24],
        "is_anonymous": False,
    }
    signing_input = (
        f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    )
    sig = hmac.new(config.JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(sig)}"

def gen_token() -> str:
    """A random refresh token."""
    return _b64url(hashlib.sha1(str(time.time()).encode() + config.JWT_SECRET.encode()).digest())[:40]

def verify_jwt(token: str) -> dict[str, Any] | None:
    """Verify a JWT signed with our JWT_SECRET. Returns the payload or None."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        signing_input = f"{parts[0]}.{parts[1]}"
        expected = hmac.new(config.JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
        actual = _b64url_decode(parts[2])
        if not hmac.compare_digest(expected, actual):
            return None
        payload = json.loads(_b64url_decode(parts[1]))
        if payload.get("exp") and payload["exp"] < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def gen_token() -> str:
    """A random refresh token."""
    return _b64url(hashlib.sha1(str(time.time()).encode() + config.JWT_SECRET.encode()).digest())[:40]


def hash_password(password: str) -> str:
    """bcrypt-hash a password (GoTrue uses bcrypt)."""
    import bcrypt  # installed transitively via supabase deps

    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        import bcrypt

        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False
