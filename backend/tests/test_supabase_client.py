import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

import pytest

from app.db import supabase as sb


@pytest.mark.parametrize("client_name", ["service_client", "anon_client"])
def test_clients_use_http1(client_name):
    """Singleton clients are hit concurrently from run_in_executor threads.
    HTTP/2 multiplexes onto one socket → parallel reads race → httpx.ReadError.
    HTTP/1.1 gives each thread its own pooled connection. Guard against regressions.
    """
    client = getattr(sb, client_name)
    session = client.postgrest.session
    assert session._transport._pool._http2 is False
