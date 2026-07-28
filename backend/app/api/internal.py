"""Internal cron endpoints. Guarded by X-Internal-Token (shared secret), not JWT.

Trigger from system cron, e.g. daily:
  curl -fsS -X POST http://127.0.0.1:8000/internal/cron/refresh-tokens \
    -H "X-Internal-Token: $INTERNAL_CRON_TOKEN"
  curl -fsS -X POST http://127.0.0.1:8000/internal/cron/prune-notifications \
    -H "X-Internal-Token: $INTERNAL_CRON_TOKEN"
"""

from __future__ import annotations

import hmac
import logging

from app.config import settings
from app.services import retention, token_refresh
from fastapi import APIRouter, Header, HTTPException, status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/cron", tags=["internal"])


def _require_internal_token(x_internal_token: str | None) -> None:
    expected = settings.INTERNAL_CRON_TOKEN
    # compare_digest, not "!=": a plain comparison leaks the shared secret one
    # byte at a time to anyone who can measure the response.
    if not expected or not hmac.compare_digest(x_internal_token or "", expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid internal token",
        )


@router.post("/refresh-tokens")
async def refresh_tokens(x_internal_token: str | None = Header(default=None)):
    """Refresh hh tokens expiring within REFRESH_THRESHOLD_DAYS."""
    _require_internal_token(x_internal_token)
    logger.info("cron: refresh-tokens invoked")
    return await token_refresh.refresh_due()


@router.post("/prune-notifications")
async def prune_notifications(x_internal_token: str | None = Header(default=None)):
    """Drop notifications nobody will ever open again (see services/retention)."""
    _require_internal_token(x_internal_token)
    logger.info("cron: prune-notifications invoked")
    return await retention.prune_notifications()
