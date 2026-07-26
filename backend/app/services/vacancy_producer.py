"""Search hh vacancies per enabled filter, dedup, push jobs into per-user queue."""

from __future__ import annotations

import asyncio
import logging
import re

from app.db.supabase import service_client
from app.services import relevance
from app.services.apply import RETRYABLE_STATUSES
from app.services.blacklist import bulk_auto_blacklist
from app.services.filters_service import _filter_to_search_params
from app.services.hh_credentials import load_api_client, persist_if_refreshed
from app.worker.queue import ApplyJob, get_user_queue

logger = logging.getLogger(__name__)

PER_PAGE = 50
MAX_PUSH_PER_RUN = 30
MAX_PAGES_PER_FILTER = 20


def _load_enabled_filters(user_id: str) -> list[dict]:
    res = (
        service_client.table("filters")
        .select(
            "id,resume_id,text,area,salary_min,experience,schedule,"
            "employment,professional_role,excluded_regex,ai_filter_enabled"
        )
        .eq("user_id", user_id)
        .eq("enabled", True)
        .execute()
    )
    return [f for f in (res.data or []) if f.get("resume_id")]


def _existing_vacancy_ids(user_id: str, vacancy_ids: list[str]) -> set[str]:
    """Vacancies already spent for this user. Rows in a RETRYABLE status never
    reached hh, so they stay eligible — matching apply._already_applied, which
    would otherwise let them through only for the producer to filter them out."""
    if not vacancy_ids:
        return set()
    res = (
        service_client.table("applications")
        .select("vacancy_id,status")
        .eq("user_id", user_id)
        .in_("vacancy_id", vacancy_ids)
        .execute()
    )
    return {
        r["vacancy_id"]
        for r in (res.data or [])
        if r.get("status") not in RETRYABLE_STATUSES
    }


def _blacklisted_employer_ids(user_id: str, employer_ids: list[str]) -> set[str]:
    if not employer_ids:
        return set()
    res = (
        service_client.table("blacklist")
        .select("employer_id")
        .eq("user_id", user_id)
        .in_("employer_id", employer_ids)
        .execute()
    )
    return {r["employer_id"] for r in (res.data or [])}


def _matches_excluded(item: dict, pat: re.Pattern | None) -> bool:
    if not pat:
        return False
    hay = " ".join(filter(None, [
        item.get("name") or "",
        (item.get("employer") or {}).get("name") or "",
        ((item.get("snippet") or {}).get("requirement") or ""),
        ((item.get("snippet") or {}).get("responsibility") or ""),
    ]))
    return bool(pat.search(hay))


async def _relevant_ids(
    loop, agent, user_id: str, resume_id: str, candidates: list[dict]
) -> set[str]:
    """Return the subset of candidate vacancy ids that are relevant.

    Cache-first: only uncached items hit the LLM. Fail-open: no agent → all
    relevant. candidates carry {id, name, snippet_requirement, snippet_responsibility}.
    """
    ids = [c["id"] for c in candidates]
    if agent is None or not ids:
        return set(ids)
    cached = await loop.run_in_executor(
        None, relevance.get_cached_verdicts, resume_id, ids
    )
    uncached = [c for c in candidates if c["id"] not in cached]
    fresh: dict[str, tuple[bool, str]] = {}
    if uncached:
        fresh = await agent.filter_relevant_vacancies(resume_id, uncached)
        await loop.run_in_executor(
            None, relevance.store_verdicts, user_id, resume_id, fresh
        )
    verdicts = {**cached, **fresh}
    # Default missing verdicts to relevant (fail-open / conservative).
    return {vid for vid in ids if verdicts.get(vid, (True, ""))[0]}


async def _filter_candidate_stream(loop, agent, client, user_id: str, f: dict):
    """Yield vacancy ids for one filter, lazily paged.

    Applies dedup / blacklist / excluded_regex / AI relevance per page, then
    yields surviving candidate ids one at a time so the caller can round-robin
    across filters. On completion (incl. early aclose) flushes the
    relations-based auto-blacklist and logs a per-filter summary.
    """
    excluded_pat: re.Pattern | None = None
    if f.get("excluded_regex"):
        try:
            excluded_pat = re.compile(f["excluded_regex"], re.IGNORECASE)
        except re.error:
            logger.warning("invalid excluded_regex on filter %s", f.get("id"))

    skipped_already = 0
    skipped_blacklist = 0
    skipped_excluded = 0
    skipped_relations = 0
    relations_blacklist: dict[str, str | None] = {}
    pages = 0

    try:
        for page in range(MAX_PAGES_PER_FILTER):
            params = _filter_to_search_params(f)
            params["per_page"] = PER_PAGE
            params["page"] = page
            logger.info(
                "producer: user=%s filter=%s search params=%s",
                user_id, f.get("id"), params,
            )
            try:
                payload = await loop.run_in_executor(
                    None, lambda p=params: client.get("vacancies", p)
                )
            except Exception:
                logger.exception("vacancy search failed for filter %s", f.get("id"))
                break

            items = payload.get("items", []) if isinstance(payload, dict) else []
            total_found = payload.get("found") if isinstance(payload, dict) else None
            pages_total = payload.get("pages") if isinstance(payload, dict) else None
            logger.info(
                "producer: user=%s filter=%s page=%d items=%d found=%s pages=%s",
                user_id, f.get("id"), page, len(items), total_found, pages_total,
            )
            if not items:
                break

            vacancy_ids = [str(it["id"]) for it in items if it.get("id")]
            employer_ids = [
                str((it.get("employer") or {}).get("id"))
                for it in items
                if (it.get("employer") or {}).get("id")
            ]
            already = await loop.run_in_executor(
                None, _existing_vacancy_ids, user_id, vacancy_ids
            )
            blacklisted = await loop.run_in_executor(
                None, _blacklisted_employer_ids, user_id, employer_ids
            )

            page_candidates: list[dict] = []
            for it in items:
                vid = str(it.get("id") or "")
                if not vid or vid in already:
                    skipped_already += 1
                    continue
                # Non-empty relations = already interacted with this vacancy
                # (responded / invited / rejected) → skip + blacklist employer
                # so we never re-apply to the same company.
                if it.get("relations"):
                    skipped_relations += 1
                    emp = it.get("employer") or {}
                    if emp.get("id"):
                        relations_blacklist[str(emp["id"])] = emp.get("name")
                    continue
                # has_test vacancies are NOT skipped — they fall through to the
                # queue and apply_one solves the test via the web session
                # (form_filler). It records form_sent on success, form_required
                # on failure, without burning an API apply attempt.
                emp_id = (it.get("employer") or {}).get("id")
                if emp_id and str(emp_id) in blacklisted:
                    skipped_blacklist += 1
                    continue
                if _matches_excluded(it, excluded_pat):
                    skipped_excluded += 1
                    continue
                snippet = it.get("snippet") or {}
                page_candidates.append({
                    "id": vid,
                    "name": it.get("name") or "",
                    "snippet_requirement": snippet.get("requirement") or "",
                    "snippet_responsibility": snippet.get("responsibility") or "",
                })

            if f.get("ai_filter_enabled") and page_candidates:
                keep = await _relevant_ids(
                    loop, agent, user_id, f["resume_id"], page_candidates
                )
                dropped = len(page_candidates) - len(keep)
                if dropped:
                    logger.info(
                        "producer: user=%s filter=%s relevance dropped %d/%d",
                        user_id, f.get("id"), dropped, len(page_candidates),
                    )
                page_candidates = [c for c in page_candidates if c["id"] in keep]

            pages += 1
            for c in page_candidates:
                yield c["id"]

            if pages_total is not None and page + 1 >= pages_total:
                break
            if len(items) < PER_PAGE:
                break
    finally:
        if relations_blacklist:
            await loop.run_in_executor(
                None, bulk_auto_blacklist, user_id, relations_blacklist
            )
        logger.info(
            "producer: user=%s filter=%s pages=%d skipped already=%d blacklist=%d "
            "excluded=%d relations=%d",
            user_id, f.get("id"), pages,
            skipped_already, skipped_blacklist, skipped_excluded, skipped_relations,
        )


async def produce_jobs(user_id: str, agent=None) -> tuple[int, int]:
    """Refill user queue from enabled filters, round-robin across filters.

    Each filter gets an equal turn (one candidate per turn) so no single
    filter can starve the others out of the shared MAX_PUSH_PER_RUN budget.
    Returns (pushed, skipped_has_test_total) — the second value is always 0
    (has_test vacancies are queued, not skipped); kept for the caller's API.
    """
    loop = asyncio.get_running_loop()
    logger.info("producer: starting for user=%s", user_id)
    filters = await loop.run_in_executor(None, _load_enabled_filters, user_id)
    logger.info(
        "producer: user=%s found %d enabled filter(s) with resume_id", user_id, len(filters)
    )
    if not filters:
        logger.warning(
            "producer: user=%s — NO enabled filter has resume_id. Создай фильтр и привяжи резюме.",
            user_id,
        )
        return 0, 0

    try:
        client = await load_api_client(user_id)
    except Exception:
        logger.exception("producer: user=%s — failed to load hh ApiClient", user_id)
        return 0, 0
    original_access = client.access_token
    queue = get_user_queue(user_id)
    pushed = 0

    streams = [_filter_candidate_stream(loop, agent, client, user_id, f) for f in filters]
    meta = [(f["resume_id"], f.get("id")) for f in filters]
    active = list(range(len(streams)))
    cursor = 0

    try:
        while pushed < MAX_PUSH_PER_RUN and active:
            idx = active[cursor % len(active)]
            try:
                vid = await streams[idx].__anext__()
            except StopAsyncIteration:
                active.remove(idx)
                continue  # list shrank — keep cursor, next turn picks the shifted item
            resume_id, filter_id = meta[idx]
            await queue.put(
                ApplyJob(
                    user_id=user_id,
                    resume_id=resume_id,
                    vacancy_id=vid,
                    filter_id=filter_id,
                )
            )
            pushed += 1
            cursor += 1
    finally:
        for s in streams:
            await s.aclose()
        await persist_if_refreshed(user_id, client, original_access)

    logger.info("producer: user=%s DONE pushed=%d total queue size=%d",
                user_id, pushed, queue.qsize())
    return pushed, 0
