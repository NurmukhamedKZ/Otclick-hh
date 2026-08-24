"""GoTrue-compatible auth endpoints (the subset the frontend + backend use).

Frontend (supabase-js):
  POST /auth/v1/signup                body {email,password,data}     → {session, user}
  POST /auth/v1/token?grant_type=password   body {email,password}    → {session, user}
  POST /auth/v1/token?grant_type=refresh_token  body {refresh_token} → {session, user}
  GET  /auth/v1/user                  Authorization: Bearer <jwt>    → {user}
  POST /auth/v1/logout                 Authorization: Bearer <jwt>   → {}

Backend (supabase-py, anon_client):
  GET  /auth/v1/user                   Authorization: Bearer <jwt>    → {user}  (validates JWT)

The user object shape (from supabase_auth UserResponse): id, aud, role, email,
email_confirmed_at, created_at, updated_at, last_sign_in_at, app_metadata,
user_metadata, identities.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from . import config
from .db import db_ctx, gen_token, hash_password, make_jwt, verify_jwt, verify_password


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def _row_to_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "app_metadata": row.get("raw_app_meta_data") or {},
        "user_metadata": row.get("raw_user_meta_data") or {},
        "aud": row.get("aud", "authenticated"),
        "role": row.get("role", "authenticated"),
        "email": row.get("email"),
        "email_confirmed_at": _iso(row.get("email_confirmed_at")),
        "confirmed_at": _iso(row.get("confirmed_at")),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
        "last_sign_in_at": _iso(row.get("last_sign_in_at")),
        "identities": [],
        "phone": row.get("phone"),
    }


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    # datetime → ISO with Z
    return v.strftime("%Y-%m-%dT%H:%M:%S.000Z")

def _auth_response(user: dict[str, Any], session: dict[str, Any] | None) -> dict[str, Any]:
    """GoTrue returns a FLAT object: session fields (access_token, refresh_token,
    expires_in, expires_at, token_type) on the top level with `user` nested.
    supabase-auth's parse_auth_response validates the body as a Session first;
    a nested {"user":...,"session":...} fails that validation → session=None →
    the frontend treats signup as "email confirmation required".
    """
    if session is None:
        return {"user": user}
    return session

def _session_row(conn: Any, user: dict[str, Any]) -> dict[str, Any]:
    user_id = user["id"]
    email = user["email"]
    access_token = make_jwt(user_id, email, role="authenticated")
    refresh_token = gen_token()
    expires_in = config.ACCESS_TOKEN_TTL
    expires_at = int(time.time()) + expires_in

    # persist refresh token
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO auth.refresh_tokens (token, user_id, revoked) VALUES (%s, %s, FALSE)",
        (refresh_token, user_id),
    )
    cur.execute(
        "UPDATE auth.users SET last_sign_in_at = now(), updated_at = now() WHERE id = %s",
        (user_id,),
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "expires_at": expires_at,
        "token_type": "bearer",
        "user": user,
    }


def signup(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    email = (body.get("email") or "").strip().lower()
    password = body.get("password")
    data = body.get("data") or {}
    if not email or not password:
        return 422, {"code": "weak_password", "message": "email and password required"}

    with db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM auth.users WHERE email = %s", (email,))
        existing = cur.fetchone()
        if existing:
            # GoTrue returns the user without a session on duplicate signup
            return 200, _auth_response(_row_to_user(existing), None)

        pw_hash = hash_password(password)
        cur.execute(
            """
            INSERT INTO auth.users
              (email, encrypted_password, email_confirmed_at, confirmed_at,
               raw_user_meta_data, raw_app_meta_data, aud, role)
            VALUES (%s, %s, now(), now(), %s, '{}'::jsonb, 'authenticated', 'authenticated')
            RETURNING *
            """,
            (email, pw_hash, _to_jsonb(data)),
        )
        row = cur.fetchone()
        user = _row_to_user(row)
        # the on_auth_user_created trigger already inserted a profile row; if not, do it
        cur.execute("SELECT 1 FROM public.profiles WHERE id = %s", (user["id"],))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO public.profiles (id) VALUES (%s) ON CONFLICT DO NOTHING",
                (user["id"],),
            )
        session = _session_row(conn, user)
        return 200, _auth_response(user, session)


def token(grant_type: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    if grant_type == "password":
        email = (body.get("email") or "").strip().lower()
        password = body.get("password") or ""
        with db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM auth.users WHERE email = %s AND encrypted_password IS NOT NULL",
                (email,),
            )
            row = cur.fetchone()
            if not row or not verify_password(password, row["encrypted_password"]):
                return 400, {"code": "invalid_credentials", "message": "Invalid login credentials"}
            user = _row_to_user(row)
            session = _session_row(conn, user)
            return 200, _auth_response(user, session)

    if grant_type == "refresh_token":
        refresh_token = body.get("refresh_token")
        if not refresh_token:
            return 400, {"code": "invalid_request", "message": "refresh_token required"}
        with db_ctx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM auth.refresh_tokens WHERE token = %s AND revoked = FALSE",
                (refresh_token,),
            )
            rt = cur.fetchone()
            if not rt:
                return 400, {"code": "invalid_grant", "message": "Invalid refresh token"}
            cur.execute("UPDATE auth.refresh_tokens SET revoked = TRUE WHERE id = %s", (rt["id"],))
            cur.execute("SELECT * FROM auth.users WHERE id = %s", (rt["user_id"],))
            row = cur.fetchone()
            if not row:
                return 400, {"code": "invalid_grant", "message": "user not found"}
            user = _row_to_user(row)
            session = _session_row(conn, user)
            return 200, _auth_response(user, session)

    return 400, {"code": "unsupported_grant_type", "message": f"grant_type={grant_type}"}


def get_user(jwt: str | None) -> tuple[int, dict[str, Any]]:
    """GET /auth/v1/user — validate the JWT and return the user record.

    This is the exact path the backend's anon_client.auth.get_user(token) hits
    to validate every request (see backend/app/api/deps.py)."""
    if not jwt:
        return 401, {"code": "invalid_jwt", "message": "missing token"}
    payload = verify_jwt(jwt)
    if payload is None:
        return 401, {"code": "invalid_jwt", "message": "invalid or expired token"}
    user_id = payload.get("sub")
    if not user_id:
        return 401, {"code": "invalid_jwt", "message": "no sub in token"}
    with db_ctx() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM auth.users WHERE id = %s", (str(user_id),))
        row = cur.fetchone()
        if not row:
            return 401, {"code": "user_not_found", "message": "user not found"}
        return 200, {"user": _row_to_user(row)}


def logout(jwt: str | None) -> tuple[int, dict[str, Any]]:
    # Revoke the session's refresh tokens. Best-effort.
    if jwt:
        payload = verify_jwt(jwt)
        if payload and payload.get("sub"):
            with db_ctx() as conn:
                conn.cursor().execute(
                    "UPDATE auth.refresh_tokens SET revoked = TRUE WHERE user_id = %s",
                    (str(payload["sub"]),),
                )
    return 200, {}


def _to_jsonb(v: Any) -> str:
    import json

    return json.dumps(v) if v is not None else None
