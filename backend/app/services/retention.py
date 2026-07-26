"""Data retention. Called from the internal cron endpoints.

`notifications` grows by up to DAILY_LIMIT rows per user per day (every
successful apply writes one) and nothing ever removed them. The pruning rules
live in the `prune_notifications` PG function (migration 025) so the delete is
one statement, not a paged read-then-delete over the API.
"""

from __future__ import annotations

import asyncio
import logging

from app.db.supabase import service_client

logger = logging.getLogger(__name__)

READ_RETENTION_DAYS = 14
MAX_RETENTION_DAYS = 90


async def prune_notifications(
    read_days: int = READ_RETENTION_DAYS, keep_days: int = MAX_RETENTION_DAYS
) -> dict:
    def _q():
        return service_client.rpc(
            "prune_notifications",
            {"p_read_days": read_days, "p_keep_days": keep_days},
        ).execute()

    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, _q)
    except Exception:
        logger.exception("retention: prune_notifications rpc failed")
        return {"status": "error", "removed": 0}
    removed = int(res.data or 0)
    logger.info("retention: pruned %d notification(s)", removed)
    return {"status": "ok", "removed": removed}
