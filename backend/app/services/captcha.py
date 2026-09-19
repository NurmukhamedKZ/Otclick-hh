"""captcha_requests lifecycle: fetch screenshot → Storage → row, mark solved, list pending.

All sync Supabase/HTTP calls run in run_in_executor — never block the event loop.
Storing the screenshot is groundwork for a future AI captcha solver.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

import requests

from app.db.supabase import service_client

logger = logging.getLogger(__name__)

SCREENSHOT_BUCKET = "captcha-screenshots"
IMAGE_FETCH_TIMEOUT = 10


def _fetch_image(captcha_url: str) -> bytes | None:
    try:
        resp = requests.get(captcha_url, timeout=IMAGE_FETCH_TIMEOUT)
        resp.raise_for_status()
        return resp.content
    except Exception:
        logger.warning("captcha: image fetch failed for %s", captcha_url, exc_info=True)
        return None


def _create_request_sync(user_id: str, captcha_url: str | None) -> dict:
    storage_path: str | None = None
    # The web apply path has no separate captcha image URL — only the DB row.
    image = _fetch_image(captcha_url) if captcha_url else None
    if image:
        path = f"{user_id}/{uuid.uuid4()}.png"
        try:
            service_client.storage.from_(SCREENSHOT_BUCKET).upload(
                path, image, {"content-type": "image/png", "upsert": "true"}
            )
            storage_path = path
        except Exception:
            logger.warning("captcha: screenshot upload failed", exc_info=True)

    res = (
        service_client.table("captcha_requests")
        .insert(
            {
                "user_id": user_id,
                "storage_path": storage_path,
                "captcha_url": captcha_url,
                "solved": False,
            }
        )
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else {}


async def create_request(user_id: str, captcha_url: str | None) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _create_request_sync, user_id, captcha_url)


def _mark_solved_sync(user_id: str) -> None:
    (
        service_client.table("captcha_requests")
        .update(
            {"solved": True, "solved_at": datetime.now(UTC).isoformat()}
        )
        .eq("user_id", user_id)
        .eq("solved", False)
        .execute()
    )


async def mark_solved(user_id: str) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _mark_solved_sync, user_id)


def _get_pending_sync(user_id: str) -> list[dict]:
    res = (
        service_client.table("captcha_requests")
        .select("*")
        .eq("user_id", user_id)
        .eq("solved", False)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


async def get_pending(user_id: str) -> list[dict]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _get_pending_sync, user_id)


def _attach_screenshot_sync(request_id: str, png: bytes) -> None:
    path = f"{uuid.uuid4()}.png"
    try:
        service_client.storage.from_(SCREENSHOT_BUCKET).upload(
            path, png, {"content-type": "image/png", "upsert": "true"}
        )
    except Exception:
        logger.warning("captcha: screenshot upload failed for request %s", request_id, exc_info=True)
        return
    (
        service_client.table("captcha_requests")
        .update({"storage_path": path})
        .eq("id", request_id)
        .execute()
    )


async def attach_screenshot(request_id: str, png: bytes) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _attach_screenshot_sync, request_id, png)


def _get_solution_sync(request_id: str) -> str | None:
    res = (
        service_client.table("captcha_requests")
        .select("solution")
        .eq("id", request_id)
        .maybe_single()
        .execute()
    )
    data = res.data if res else None
    return (data or {}).get("solution")


async def get_solution(request_id: str) -> str | None:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _get_solution_sync, request_id)


def _clear_solution_sync(request_id: str) -> None:
    (
        service_client.table("captcha_requests")
        .update({"solution": None})
        .eq("id", request_id)
        .execute()
    )


async def clear_solution(request_id: str) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _clear_solution_sync, request_id)


def _submit_solution_sync(user_id: str, solution: str) -> None:
    (
        service_client.table("captcha_requests")
        .update({"solution": solution})
        .eq("user_id", user_id)
        .eq("solved", False)
        .execute()
    )


async def submit_solution(user_id: str, solution: str) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _submit_solution_sync, user_id, solution)
