"""Download the user's hh resume as a PDF for the extension's file inputs.

`ApiClient.request` always JSON-decodes the response, so the binary is fetched
with a plain `requests.get` carrying the same bearer token.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import unquote, urlparse

import requests

from app.services.form_filler import load_resume
from app.services.hh_credentials import load_api_client

logger = logging.getLogger(__name__)

TIMEOUT_S = 30


async def fetch_resume_pdf(user_id: str) -> tuple[bytes, str] | None:
    """(pdf bytes, filename) or None when hh has no downloadable resume."""
    try:
        resume = await load_resume(user_id)
    except Exception:
        logger.warning("extension resume: load failed for %s", user_id, exc_info=True)
        return None
    url = ((resume.get("download") or {}).get("pdf") or {}).get("url")
    if not url:
        return None
    try:
        client = await load_api_client(user_id)
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None,
            lambda: requests.get(
                url,
                headers={"Authorization": f"Bearer {client.access_token}"},
                timeout=TIMEOUT_S,
            ),
        )
    except Exception:
        logger.warning("extension resume: download failed for %s", user_id, exc_info=True)
        return None
    if resp.status_code != 200 or not resp.content:
        logger.info("extension resume: hh returned %s for %s", resp.status_code, user_id)
        return None
    # hh embeds the candidate's name in the path, percent-encoded and non-ASCII.
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1]) or "resume.pdf"
    return resp.content, name
