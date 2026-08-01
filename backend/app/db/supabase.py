import httpx
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

from app.config import settings


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
