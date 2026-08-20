import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

import pytest
from pydantic import ValidationError


def test_ai_positioning_defaults_to_balanced():
    from app.config import Settings

    assert Settings.model_fields["AI_POSITIONING"].default == "balanced"


def test_ai_positioning_rejects_unknown_value():
    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(AI_POSITIONING="aggressive")
