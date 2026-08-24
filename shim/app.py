"""FastAPI shim that replaces Kong + GoTrue + PostgREST + Storage for Otclick-hh.

Listens on 0.0.0.0:54321 (the same port Kong would). The backend connects to
SUPABASE_URL=http://kong:8000 in Docker; for local run we point it at
http://127.0.0.1:54321 and add `kong` to the hosts file (or rewrite SUPABASE_URL).

Run:
    .venv/Scripts/python.exe -m shim.app
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from . import auth as auth_api
from . import config
from . import postgrest
from . import storage as storage_api
from .db import verify_jwt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("shim")

app = FastAPI(title="Otclick Supabase Shim", version="0.1.0")

# CORS: the browser frontend (localhost:3000) calls this shim (localhost:54321)
# cross-origin. Kong would set these in production; the shim must too, or
# supabase-js fetch() fails with "TypeError: Failed to fetch".
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["content-range", "Content-Range", "x-total-count"],
)


# ── shared helpers ─────────────────────────────────────────────────────────

def _check_apikey(apikey: str | None, authorization: str | None) -> bool:
    """Accept either the anon or the service_role key (both are valid for the
    shim — we don't enforce RLS, the service_role bypasses it anyway)."""
    if not apikey:
        # Some SDKs send only Authorization
        if authorization and authorization.startswith("Bearer "):
            tok = authorization[7:]
            if tok in (config.ANON_KEY, config.SERVICE_ROLE_KEY):
                return True
            # Could be a user JWT — that's fine too for reads
            if verify_jwt(tok):
                return True
        return False
    return apikey in (config.ANON_KEY, config.SERVICE_ROLE_KEY)


def _pgrst_error(status: int, message: str, code: str = "PGRST000") -> JSONResponse:
    return JSONResponse(status_code=status, content={"message": message, "code": code})


def _deserialize_body(body: bytes, content_type: str) -> Any:
    if not body:
        return None
    if isinstance(body, str):
        body = body.encode()
    try:
        return json.loads(body)
    except Exception:
        return body


# ── health ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "shim"}


# ── PostgREST: /rest/v1/{table} ───────────────────────────────────────────

@app.api_route("/rest/v1/{table}", methods=["GET", "POST", "PATCH", "PUT", "DELETE", "HEAD"])
async def rest_table(
    table: str,
    request: Request,
    apikey: str | None = Header(None, alias="apikey"),
    authorization: str | None = Header(None),
    accept: str = Header("application/json"),
    prefer: str = Header(""),
):
    if not _check_apikey(apikey, authorization):
        return _pgrst_error(401, "Invalid API key", "PGRST301")
    # RPC is a sub-path of /rest/v1
    if table == "rpc":
        return _pgrst_error(404, "rpc requires a function name", "PGRST204")

    raw_body = await request.body()
    body = _deserialize_body(raw_body, request.headers.get("content-type", ""))
    # collect query params preserving order + duplicates
    params = [(k, v) for k, v in request.query_params.multi_items()]
    headers = {"prefer": prefer, "accept": accept}

    try:
        status, data, resp_headers = postgrest.query(table, request.method, params, body, headers)
    except Exception as e:
        log.exception("postgrest query failed: %s", table)
        return _pgrst_error(400, str(e))

    if request.method == "HEAD":
        # HEAD returns 200 with only headers (Content-Range), never a body.
        # Bypasses the 204 branch below, which would drop the count header.
        return Response(status_code=status, headers=resp_headers)
    if status == 204 or data is None:
        return Response(status_code=204, headers=resp_headers)
    resp = JSONResponse(status_code=status, content=data, headers=resp_headers)
    return resp


# ── PostgREST: /rest/v1/rpc/{name} ─────────────────────────────────────────

@app.api_route("/rest/v1/rpc/{name}", methods=["POST", "GET"])
async def rest_rpc(
    name: str,
    request: Request,
    apikey: str | None = Header(None, alias="apikey"),
    authorization: str | None = Header(None),
    accept: str = Header("application/json"),
):
    if not _check_apikey(apikey, authorization):
        return _pgrst_error(401, "Invalid API key", "PGRST301")
    raw_body = await request.body()
    args = _deserialize_body(raw_body, request.headers.get("content-type", "")) or {}
    if not isinstance(args, dict):
        return _pgrst_error(400, "rpc body must be a JSON object", "PGRST100")
    try:
        status, data, _ = postgrest.rpc(name, args)
    except Exception as e:
        log.exception("rpc %s failed", name)
        return _pgrst_error(400, str(e))
    # PostgREST wraps single-object returns in an array when Accept is the
    # default; supabase-py's RPCFilterRequestBuilder uses SingleAPIResponse
    # so a bare object is fine. Match: return the value as-is.
    return JSONResponse(status_code=status, content=data)


# ── Auth: /auth/v1/* ───────────────────────────────────────────────────────

@app.post("/auth/v1/signup")
async def auth_signup(request: Request):
    body = _deserialize_body(await request.body(), request.headers.get("content-type", "")) or {}
    status, data = auth_api.signup(body)
    return JSONResponse(status_code=status, content=data)


@app.post("/auth/v1/token")
async def auth_token(
    request: Request,
    grant_type: str = Query(...),
):
    body = _deserialize_body(await request.body(), request.headers.get("content-type", "")) or {}
    status, data = auth_api.token(grant_type, body)
    return JSONResponse(status_code=status, content=data)


@app.get("/auth/v1/user")
async def auth_get_user(authorization: str | None = Header(None)):
    jwt = authorization[7:] if authorization and authorization.startswith("Bearer ") else None
    status, data = auth_api.get_user(jwt)
    return JSONResponse(status_code=status, content=data)


@app.put("/auth/v1/user")
async def auth_put_user(request: Request, authorization: str | None = Header(None)):
    jwt = authorization[7:] if authorization and authorization.startswith("Bearer ") else None
    if not jwt or verify_jwt(jwt) is None:
        return JSONResponse(status_code=401, content={"code": "invalid_jwt", "message": "invalid token"})
    # We don't fully implement profile updates; return the existing user.
    status, data = auth_api.get_user(jwt)
    return JSONResponse(status_code=status, content=data)


@app.post("/auth/v1/logout")
async def auth_logout(authorization: str | None = Header(None)):
    jwt = authorization[7:] if authorization and authorization.startswith("Bearer ") else None
    status, data = auth_api.logout(jwt)
    return JSONResponse(status_code=status, content=data)


# ── Storage: /storage/v1/* ────────────────────────────────────────────────

@app.post("/storage/v1/object/{bucket}/{path:path}")
async def storage_upload(
    bucket: str,
    path: str,
    request: Request,
    apikey: str | None = Header(None, alias="apikey"),
    authorization: str | None = Header(None),
    content_type: str = Header("application/octet-stream"),
    x_upsert: str | None = Header(None, alias="x-upsert"),
):
    if not _check_apikey(apikey, authorization):
        return _pgrst_error(401, "Invalid API key")
    data = await request.body()
    result = storage_api.upload(bucket, path, data, content_type)
    return JSONResponse(status_code=200, content=result)


@app.put("/storage/v1/object/{bucket}/{path:path}")
async def storage_update(
    bucket: str,
    path: str,
    request: Request,
    apikey: str | None = Header(None, alias="apikey"),
    authorization: str | None = Header(None),
    content_type: str = Header("application/octet-stream"),
):
    if not _check_apikey(apikey, authorization):
        return _pgrst_error(401, "Invalid API key")
    data = await request.body()
    result = storage_api.update(bucket, path, data, content_type)
    return JSONResponse(status_code=200, content=result)


@app.post("/storage/v1/object/sign/{bucket}/{path:path}")
async def storage_sign(
    bucket: str,
    path: str,
    request: Request,
    apikey: str | None = Header(None, alias="apikey"),
    authorization: str | None = Header(None),
):
    if not _check_apikey(apikey, authorization):
        return _pgrst_error(401, "Invalid API key")
    body = _deserialize_body(await request.body(), request.headers.get("content-type", "")) or {}
    expires_in = int(body.get("expiresIn", 3600))
    result = storage_api.create_signed_url(bucket, path, expires_in)
    return JSONResponse(status_code=200, content=result)


@app.get("/storage/v1/object/sign/{bucket}/{path:path}")
async def storage_serve_signed(
    bucket: str,
    path: str,
    token: str | None = Query(None),
):
    if not token or not storage_api.verify_signed_url(bucket, path, token):
        return _pgrst_error(403, "invalid or expired signed URL")
    result = storage_api.read_file(bucket, path)
    if result is None:
        return _pgrst_error(404, "object not found")
    data, ct = result
    return Response(content=data, media_type=ct)


@app.get("/storage/v1/object/public/{bucket}/{path:path}")
async def storage_public(bucket: str, path: str):
    result = storage_api.read_file(bucket, path)
    if result is None:
        return _pgrst_error(404, "object not found")
    data, ct = result
    return Response(content=data, media_type=ct)


@app.post("/storage/v1/bucket")
async def storage_create_bucket(request: Request, apikey: str | None = Header(None, alias="apikey")):
    if not _check_apikey(apikey, None):
        return _pgrst_error(401, "Invalid API key")
    body = _deserialize_body(await request.body(), request.headers.get("content-type", "")) or {}
    name = body.get("name") or body.get("id")
    if not name:
        return _pgrst_error(400, "bucket name required")
    return JSONResponse(status_code=200, content=storage_api.create_bucket(name))


@app.get("/storage/v1/bucket/{bucket}")
async def storage_get_bucket(bucket: str, apikey: str | None = Header(None, alias="apikey")):
    if not _check_apikey(apikey, None):
        return _pgrst_error(401, "Invalid API key")
    return JSONResponse(status_code=200, content={"name": bucket, "id": bucket, "public": False})


# ── Realtime stub: the backend doesn't use realtime over the API (it's a
# browser feature), so a 404 is fine. The frontend's realtime bridge will
# just not receive pushes — acceptable degradation. ────────────────────────

@app.api_route("/realtime/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def realtime_stub(path: str):
    return JSONResponse(status_code=501, content={"message": "realtime not available in shim mode"})


@app.websocket("/realtime/v1/websocket")
async def realtime_ws(websocket):
    # Reject the upgrade — the frontend falls back to polling.
    await websocket.close(code=1011)


def _ensure_buckets() -> None:
    """Create the captcha-screenshots bucket directory at startup."""
    for b in ("captcha-screenshots",):
        storage_api.ensure_bucket(b)


@app.on_event("startup")
def _startup() -> None:
    _ensure_buckets()
    log.info("shim listening on :54321 — pointing backend at http://127.0.0.1:54321")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=54321, log_level="info")
