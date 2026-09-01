import json
from typing import Any

import httpx
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

from app.config import settings


def _jsonify(value: Any) -> Any:
    """Serialize dict/list values to JSON strings for jsonb columns.

    postgrest 2.30 does not auto-adapt Python dicts/lists into jsonb (raises
    "can't adapt type 'dict'"). Wrapping them as JSON strings makes the shim's
    PostgREST layer land them correctly. Scalars pass through unchanged.
    """
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def jsonb_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `row` with every dict/list value JSON-encoded.

    Call this on any row about to be inserted/upserted/updated through the
    postgrest client, so jsonb columns receive a JSON string instead of a raw
    Python object the client can't adapt.
    """
    return {k: _jsonify(v) for k, v in row.items()}

def _make_client(key: str) -> Client:
    # Force HTTP/1.1. These clients are singletons called concurrently from
    # run_in_executor worker threads. HTTP/2 multiplexes every request onto a
    # single socket, so parallel reads from different threads race and surface
    # as `httpx.ReadError [Errno 35] Resource temporarily unavailable`. HTTP/1.1
    # hands each thread its own pooled connection, which httpx is thread-safe for.
    httpx_client = httpx.Client(http2=False, timeout=120, follow_redirects=True)
    return create_client(
        settings.SUPABASE_URL,
        key,
        SyncClientOptions(httpx_client=httpx_client),
    )


# Bypasses RLS — use for all data writes and sensitive reads (hh_credentials)
service_client: Client = _make_client(settings.SUPABASE_SERVICE_ROLE_KEY)

# Respects RLS — use for JWT validation only
anon_client: Client = _make_client(settings.SUPABASE_ANON_KEY)
