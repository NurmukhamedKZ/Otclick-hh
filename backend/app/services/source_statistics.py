"""Atomic cumulative statistics for vacancy search sources."""

from __future__ import annotations

from app.db.supabase import service_client


def source_ids_for_vacancy(pipeline_id: str) -> list[str]:
    res = (
        service_client.table("vacancy_pipeline_sources")
        .select("source_id")
        .eq("vacancy_id", pipeline_id)
        .execute()
    )
    return [str(row["source_id"]) for row in (res.data or []) if row.get("source_id")]


def increment(
    source_ids: list[str],
    *,
    new: int = 0,
    duplicate: int = 0,
    hard_filtered: int = 0,
    score_error: int = 0,
) -> None:
    ids = list(dict.fromkeys(str(source_id) for source_id in source_ids if source_id))
    if not ids:
        return
    service_client.rpc(
        "increment_vacancy_source_stats",
        {
            "p_source_ids": ids,
            "p_new": max(0, int(new)),
            "p_duplicate": max(0, int(duplicate)),
            "p_hard_filtered": max(0, int(hard_filtered)),
            "p_score_error": max(0, int(score_error)),
        },
    ).execute()


def increment_for_vacancy(pipeline_id: str, **counts: int) -> None:
    increment(source_ids_for_vacancy(pipeline_id), **counts)
