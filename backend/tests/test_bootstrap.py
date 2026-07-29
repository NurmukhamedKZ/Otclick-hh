"""infra/bootstrap.py must produce a .env whose keys all agree with JWT_SECRET."""

import base64
import hashlib
import hmac
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

spec = importlib.util.spec_from_file_location("bootstrap", ROOT / "infra" / "bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def _parse(text: str) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in text.splitlines()
        if line and not line.startswith("#") and "=" in line
    )


def _valid_signature(token: str, secret: str) -> bool:
    signing_input, _, sig = token.rpartition(".")
    expected = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return sig == base64.urlsafe_b64encode(expected).rstrip(b"=").decode()


def test_rendered_env_is_complete_and_consistent():
    values = bootstrap.generate()
    env = _parse(bootstrap.render((ROOT / ".env.example").read_text(), values))

    for key in values:
        assert env[key], f"{key} left empty"

    secret = env["JWT_SECRET"]
    assert _valid_signature(env["ANON_KEY"], secret)
    assert _valid_signature(env["SERVICE_ROLE_KEY"], secret)
    # The stack-level and app-level copies must be the same token, or everything 401s.
    assert env["ANON_KEY"] == env["SUPABASE_ANON_KEY"] == env["NEXT_PUBLIC_SUPABASE_ANON_KEY"]
    assert env["SERVICE_ROLE_KEY"] == env["SUPABASE_SERVICE_ROLE_KEY"]
    assert len(base64.urlsafe_b64decode(env["FERNET_KEY"])) == 32
