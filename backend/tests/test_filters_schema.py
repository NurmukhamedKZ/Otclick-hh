import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")


def test_filter_create_defaults_ai_filter_enabled_false():
    from app.schemas.filters import FilterCreate
    assert FilterCreate(resume_id="r1").ai_filter_enabled is False


def test_filter_update_accepts_ai_filter_enabled():
    from app.schemas.filters import FilterUpdate
    u = FilterUpdate(ai_filter_enabled=False)
    assert u.model_dump(exclude_unset=True) == {"ai_filter_enabled": False}


def test_filter_response_has_ai_filter_enabled():
    from app.schemas.filters import FilterResponse
    r = FilterResponse(id="x", ai_filter_enabled=False)
    assert r.ai_filter_enabled is False
