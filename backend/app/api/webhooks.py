"""Public payment webhooks. No JWT — authenticated by the Polar signature.

Subscribe the endpoint to `order.paid`, `subscription.active`,
`subscription.canceled` and `subscription.revoked` in the Polar dashboard.
Signature verification follows Standard Webhooks (SDK's validate_event).
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request, status
from polar_sdk.webhooks import WebhookVerificationError

from app.services import billing as billing_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/polar")
async def polar(request: Request):
    raw = await request.body()
    try:
        event = billing_service.verify_polar_webhook(raw, dict(request.headers))
    except WebhookVerificationError:
        logger.warning("polar webhook bad signature")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="bad signature"
        ) from None
    except Exception:
        # Valid signature but an event type this SDK version cannot parse —
        # acknowledge instead of retrying forever.
        logger.warning("polar webhook unparsable payload", exc_info=True)
        return {"ok": True, "ignored": True}

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, billing_service.process_polar_event, event)
    except Exception:
        logger.exception("polar webhook processing failed")
    return {"ok": True}
