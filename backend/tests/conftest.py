"""Shared test setup.

Several modules keep process-local caches (hh web sessions, ApiClients, verified
JWTs, negotiation states, one-shot notifications). They are correct in a
long-lived worker but leak state between tests, so clear them per test.
"""

import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

import pytest


@pytest.fixture(autouse=True)
def _clear_process_caches():
    def _clear():
        from app.api import deps
        from app.services import form_filler, hh_credentials, notifications
        from app.worker import recruiter_poll

        form_filler._sessions.clear()
        hh_credentials._clients.clear()
        deps._token_cache.clear()
        notifications._once_sent.clear()
        recruiter_poll._states_cache.clear()

    _clear()
    yield
    _clear()
