"""Storage API (the subset the backend uses: upload + create_signed_url +
get_public_url for the captcha-screenshots bucket). Files live on disk."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from . import config


def _bucket_root(bucket: str) -> Path:
    root = config.STORAGE_ROOT / bucket
    root.mkdir(parents=True, exist_ok=True)
    return root


def upload(bucket: str, path: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
    """POST /storage/v1/object/{bucket}/{path} — store the file on disk."""
    safe = _safe_path(path)
    target = _bucket_root(bucket) / safe
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"Key": f"{bucket}/{safe}", "Id": str(uuid.uuid4())}


def update(bucket: str, path: str, data: bytes) -> dict:
    """PUT /storage/v1/object/{bucket}/{path} — overwrite."""
    return upload(bucket, path, data)


def create_signed_url(bucket: str, path: str, expires_in: int = 3600) -> dict:
    """POST /storage/v1/object/sign/{bucket}/{path} — return a signed URL.

    The frontend opens these in a browser tab to view captcha screenshots.
    We sign with an HMAC of (path|expiry) using JWT_SECRET and verify on GET.
    """
    import hashlib
    import hmac
    import base64

    exp = int(time.time()) + expires_in
    msg = f"{bucket}/{path}|{exp}".encode()
    sig = hmac.new(config.JWT_SECRET.encode(), msg, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(f"{exp}.{sig}".encode()).decode().rstrip("=")
    public_url = f"{config.SUPABASE_PUBLIC_URL.rstrip('/')}/storage/v1/object/sign/{bucket}/{path}?token={token}"
    return {"signedURL": public_url}


def get_public_url(bucket: str, path: str) -> str:
    return f"{config.SUPABASE_PUBLIC_URL.rstrip('/')}/storage/v1/object/public/{bucket}/{path}"


def verify_signed_url(bucket: str, path: str, token: str) -> bool:
    import hashlib
    import hmac
    import base64

    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + pad).decode()
        exp_str, sig = raw.split(".", 1)
        exp = int(exp_str)
        if exp < int(time.time()):
            return False
        msg = f"{bucket}/{path}|{exp}".encode()
        expected = hmac.new(config.JWT_SECRET.encode(), msg, hashlib.sha256).digest()
        return hmac.compare_digest(expected, sig.encode() if isinstance(sig, str) else sig)
    except Exception:
        return False


def read_file(bucket: str, path: str) -> tuple[bytes, str] | None:
    safe = _safe_path(path)
    target = _bucket_root(bucket) / safe
    if not target.is_file():
        return None
    # naive content type
    ct = "image/png" if target.suffix.lower() == ".png" else "application/octet-stream"
    return target.read_bytes(), ct


def _safe_path(path: str) -> str:
    """Reject path traversal."""
    p = Path(path)
    parts = [part for part in p.parts if part not in ("", ".", "/")]
    safe = Path(*parts) if parts else Path(uuid.uuid4().hex)
    # Final path must remain inside the bucket root
    return str(safe)


def ensure_bucket(bucket: str) -> None:
    _bucket_root(bucket)


def create_bucket(bucket: str) -> dict:
    ensure_bucket(bucket)
    return {"name": bucket, "id": bucket}
