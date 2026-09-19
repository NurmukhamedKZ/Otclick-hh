import asyncio
import hashlib
import logging
import time

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db.supabase import anon_client

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=True)

# Validating every request against GoTrue is a network round trip per call, and
# the dashboard polls /api/worker/status every 5s per open tab. Cache the
# verified result briefly — short enough that a signed-out token stops working
# within a minute, long enough to collapse the polling traffic.
_TOKEN_CACHE_TTL_S = 60.0
_token_cache: dict[str, tuple[float, str]] = {}


def _cache_key(token: str) -> str:
    # Don't keep raw tokens in a process-wide dict.
    return hashlib.sha256(token.encode()).hexdigest()


def _purge_expired(now: float) -> None:
    if len(_token_cache) < 512:
        return
    for k, (exp, _) in list(_token_cache.items()):
        if exp <= now:
            _token_cache.pop(k, None)


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    """Validate Supabase JWT → return user_id (uuid string)."""
    now = time.monotonic()
    key = _cache_key(creds.credentials)
    hit = _token_cache.get(key)
    if hit and hit[0] > now:
        return hit[1]

    loop = asyncio.get_running_loop()
    try:
        # anon_client is a sync Supabase client — run in executor to avoid blocking event loop
        res = await loop.run_in_executor(None, anon_client.auth.get_user, creds.credentials)
    except Exception as ex:
        # The upstream message can carry internal detail — log it, don't return it.
        logger.info("auth: token rejected: %s", ex)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
        ) from ex
    user = getattr(res, "user", None)
    if user is None or not getattr(user, "id", None):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
        )
    _purge_expired(now)
    _token_cache[key] = (now + _TOKEN_CACHE_TTL_S, user.id)
    return user.id
