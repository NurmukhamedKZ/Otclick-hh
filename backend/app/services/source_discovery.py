"""Incremental discovery from persistent Search Sources.

This module deliberately has no dependency on ApplyJob/apply_one. Its only
output is PostgreSQL `vacancy_pipeline` rows. Sending is a separate future
worker fed exclusively by approved send jobs.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from urllib.parse import urlencode

from app.db.supabase import service_client
from app.hh import web
from app.hh.page_json import find_state
from app.services import source_statistics
from app.services.form_filler import (
    WebSessionExpired,
    load_web_session,
    report_dead_session,
)
from app.services.vacancy_pipeline import persist_discovered

logger = logging.getLogger(__name__)

INITIAL_SCAN_PAGES = 3
INCREMENTAL_MAX_PAGES = 20


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_enabled_sources(user_id: str) -> list[dict]:
    res = (
        service_client.table("vacancy_search_sources")
        .select("id,resume_id,name,source_type,query_pairs,cursor,enabled")
        .eq("user_id", user_id)
        .eq("enabled", True)
        .in_("source_type", ["search_url", "hh_autosearch"])
        .execute()
    )
    return res.data or []


def _existing_application_ids(user_id: str, vacancy_ids: list[str]) -> set[str]:
    if not vacancy_ids:
        return set()
    res = (
        service_client.table("applications")
        .select("vacancy_id")
        .eq("user_id", user_id)
        .in_("vacancy_id", vacancy_ids)
        .execute()
    )
    return {str(row["vacancy_id"]) for row in (res.data or []) if row.get("vacancy_id")}


def _existing_pipeline_ids(user_id: str, vacancy_ids: list[str]) -> set[str]:
    if not vacancy_ids:
        return set()
    res = (
        service_client.table("vacancy_pipeline")
        .select("hh_vacancy_id")
        .eq("user_id", user_id)
        .in_("hh_vacancy_id", vacancy_ids)
        .execute()
    )
    return {
        str(row["hh_vacancy_id"])
        for row in (res.data or [])
        if row.get("hh_vacancy_id")
    }


def _update_source(source_id: str, **changes) -> None:
    service_client.table("vacancy_search_sources").update(
        {**changes, "updated_at": _now()}
    ).eq("id", source_id).execute()


def _request_pairs(source: dict, page: int) -> list[tuple[str, str]]:
    """Preserve duplicate HH query keys exactly as stored."""
    pairs: list[tuple[str, str]] = []
    for item in source.get("query_pairs") or []:
        key = str((item or {}).get("key") or "")
        if not key or key in {"page", "items_on_page", "order_by"}:
            continue
        pairs.append((key, str((item or {}).get("value") or "")))
    pairs.append(("order_by", "publication_time"))
    pairs.append(("page", str(page)))
    return pairs


def _cursor_stats(
    cursor: dict,
    *,
    fetched: int,
    persisted: int,
    skipped_applied: int,
    error: bool,
) -> dict[str, int]:
    previous = cursor.get("stats") or {}
    return {
        "runs": int(previous.get("runs") or 0) + 1,
        "fetched": int(previous.get("fetched") or 0) + fetched,
        "persisted": int(previous.get("persisted") or 0) + persisted,
        "skipped_applied": int(previous.get("skipped_applied") or 0) + skipped_applied,
        "errors": int(previous.get("errors") or 0) + (1 if error else 0),
    }


def _failure_cursor(cursor: dict, checked_at: str, error: str) -> dict:
    next_cursor = dict(cursor)
    next_cursor["stats"] = _cursor_stats(
        cursor,
        fetched=0,
        persisted=0,
        skipped_applied=0,
        error=True,
    )
    next_cursor["last_run"] = {
        "checked_at": checked_at,
        "fetched": 0,
        "persisted": 0,
        "skipped_applied": 0,
        "error": error[:1000],
    }
    return next_cursor


async def _search_page(user_id: str, source: dict, page: int) -> tuple[list[dict], int]:
    session = await load_web_session(user_id)
    url = f"{web.SEARCH_URL}?{urlencode(_request_pairs(source, page))}"
    resp = await asyncio.to_thread(web._get, session, user_id, url)
    data = find_state(resp.text, "vacancySearchResult")
    raw_items = data.get("vacancies") or []
    items = [
        item
        for item in (web._normalise_vacancy(raw) for raw in raw_items)
        if item.get("id")
    ]
    return items, int(data.get("totalResults") or 0)


async def discover_source(user_id: str, source: dict) -> dict[str, int | bool]:
    source_id = str(source["id"])
    cursor = source.get("cursor") or {}
    previous_head = {str(v) for v in (cursor.get("head_ids") or []) if v}
    initial = not previous_head
    page_limit = INITIAL_SCAN_PAGES if initial else INCREMENTAL_MAX_PAGES

    fetched = 0
    persisted = 0
    skipped_applied = 0
    new_count = 0
    duplicate_count = 0
    overlap_found = False
    first_page_ids: list[str] = []
    checked_at = _now()
    await asyncio.to_thread(_update_source, source_id, last_checked_at=checked_at, last_error=None)

    try:
        for page in range(page_limit):
            items, total = await _search_page(user_id, source, page)
            if not items:
                overlap_found = bool(previous_head) or initial
                break
            ids = [str(item["id"]) for item in items]
            if page == 0:
                first_page_ids = ids[:40]
            applied, existing_pipeline = await asyncio.gather(
                asyncio.to_thread(_existing_application_ids, user_id, ids),
                asyncio.to_thread(_existing_pipeline_ids, user_id, ids),
            )

            stop_after_page = False
            for item in items:
                vid = str(item["id"])
                if previous_head and vid in previous_head:
                    overlap_found = True
                    stop_after_page = True
                    break
                fetched += 1
                if vid in applied:
                    skipped_applied += 1
                    continue
                await asyncio.to_thread(
                    persist_discovered,
                    user_id=user_id,
                    resume_id=source.get("resume_id"),
                    vacancy=item,
                    source_id=source_id,
                )
                persisted += 1
                if vid in existing_pipeline:
                    duplicate_count += 1
                else:
                    new_count += 1
                    existing_pipeline.add(vid)

            if stop_after_page:
                break
            if total and (page + 1) * max(len(items), 1) >= total:
                overlap_found = True
                break
    except WebSessionExpired as ex:
        await report_dead_session(user_id, ex)
        message = str(ex)
        await asyncio.to_thread(
            _update_source,
            source_id,
            cursor=_failure_cursor(cursor, checked_at, message),
            last_error=message[:1000],
        )
        raise
    except Exception as ex:
        message = str(ex)
        await asyncio.to_thread(
            _update_source,
            source_id,
            cursor=_failure_cursor(cursor, checked_at, message),
            last_error=message[:1000],
        )
        raise

    await asyncio.to_thread(
        source_statistics.increment,
        [source_id],
        new=new_count,
        duplicate=duplicate_count,
    )

    warning = None
    if not initial and not overlap_found:
        warning = "cursor_overlap_not_found_within_scan_limit"

    new_cursor = {
        "version": 2,
        "head_ids": first_page_ids,
        "checked_at": checked_at,
        "overlap_found": overlap_found,
        "stats": _cursor_stats(
            cursor,
            fetched=fetched,
            persisted=persisted,
            skipped_applied=skipped_applied,
            error=False,
        ),
        "last_run": {
            "checked_at": checked_at,
            "fetched": fetched,
            "persisted": persisted,
            "new": new_count,
            "duplicate": duplicate_count,
            "skipped_applied": skipped_applied,
            "overlap_found": overlap_found,
            "error": warning,
        },
    }
    await asyncio.to_thread(
        _update_source,
        source_id,
        cursor=new_cursor,
        last_success_at=_now(),
        last_error=warning,
    )
    return {
        "fetched": fetched,
        "persisted": persisted,
        "new": new_count,
        "duplicate": duplicate_count,
        "skipped_applied": skipped_applied,
        "overlap_found": overlap_found,
    }


async def discover_user(user_id: str) -> dict[str, int]:
    sources = await asyncio.to_thread(_load_enabled_sources, user_id)
    summary = {"sources": len(sources), "fetched": 0, "persisted": 0, "errors": 0}
    for source in sources:
        try:
            result = await discover_source(user_id, source)
        except WebSessionExpired:
            summary["errors"] += 1
            break
        except Exception:
            summary["errors"] += 1
            logger.exception("discovery failed user=%s source=%s", user_id, source.get("id"))
            continue
        summary["fetched"] += int(result["fetched"])
        summary["persisted"] += int(result["persisted"])
    logger.info("discovery user=%s summary=%s", user_id, summary)
    return summary
