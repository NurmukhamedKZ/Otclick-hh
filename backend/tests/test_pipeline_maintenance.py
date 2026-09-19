import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_rescore_stale_scores_only_rows_requeued_by_this_action():
    from app.services import pipeline_maintenance as svc

    rows = [
        {"id": "p1", "status": "scored", "score_stale": True},
        {"id": "p2", "status": "review", "score_stale": True},
    ]
    llm = MagicMock()
    with (
        patch.object(svc, "_stale_score_rows", new=AsyncMock(return_value=rows)),
        patch.object(svc.candidate_context_service, "load_candidate_context", new=AsyncMock(return_value={"version": 1})) as context,
        patch.object(svc.selection_rules, "load_active_rules", new=AsyncMock(return_value=[])) as rules,
        patch.object(svc, "HHAgent", return_value=MagicMock(llm=llm)),
        patch.object(svc, "_requeue_score", side_effect=[True, False]) as requeue,
        patch.object(svc.pipeline_scoring, "score_one", new=AsyncMock(return_value="scored")) as score_one,
    ):
        result = await svc.rescore_stale("u1")

    assert result["matched_stale"] == 2
    assert result["requeued"] == 1
    assert result["scoring"]["found"] == 1
    assert result["scoring"]["scored"] == 1
    assert requeue.call_count == 2
    score_one.assert_awaited_once()
    args = score_one.await_args.args
    kwargs = score_one.await_args.kwargs
    assert args[0] == "u1"
    assert args[1]["id"] == "p1"
    assert args[1]["status"] == "discovered"
    assert kwargs["llm"] is llm
    context.assert_awaited_once_with("u1")
    rules.assert_awaited_once_with("u1")


@pytest.mark.asyncio
async def test_rescore_loads_context_before_requeueing_anything():
    from app.services import pipeline_maintenance as svc

    rows = [{"id": "p1", "status": "scored", "score_stale": True}]
    with (
        patch.object(svc, "_stale_score_rows", new=AsyncMock(return_value=rows)),
        patch.object(
            svc.candidate_context_service,
            "load_candidate_context",
            new=AsyncMock(side_effect=RuntimeError("profile unavailable")),
        ),
        patch.object(svc.selection_rules, "load_active_rules", new=AsyncMock(return_value=[])),
        patch.object(svc, "_requeue_score") as requeue,
    ):
        with pytest.raises(RuntimeError):
            await svc.rescore_stale("u1")

    requeue.assert_not_called()


@pytest.mark.asyncio
async def test_stale_cover_candidates_exclude_user_edited_drafts():
    from app.services import pipeline_maintenance as svc

    rows = [
        {
            "id": "safe",
            "status": "letter_draft",
            "cover_stale": True,
            "cover_letter_meta": {"edited_by_user": False},
        },
        {
            "id": "edited",
            "status": "letter_draft",
            "cover_stale": True,
            "cover_letter_meta": {"edited_by_user": True},
        },
        {
            "id": "fresh",
            "status": "letter_draft",
            "cover_stale": False,
            "cover_letter_meta": {"edited_by_user": False},
        },
    ]
    with patch.object(
        svc.vacancy_review_service,
        "list_vacancies",
        new=AsyncMock(return_value=rows),
    ) as list_rows:
        result = await svc._stale_cover_rows("u1")

    assert [row["id"] for row in result] == ["safe"]
    assert list_rows.await_args.kwargs["statuses"] == ["letter_draft"]


@pytest.mark.asyncio
async def test_regenerate_stale_covers_calls_writer_only_for_safe_rows():
    from app.services import pipeline_maintenance as svc

    rows = [{"id": "p1"}, {"id": "p2"}]
    generate = AsyncMock(side_effect=[{"id": "p1"}, RuntimeError("llm error")])
    with (
        patch.object(svc, "_stale_cover_rows", new=AsyncMock(return_value=rows)),
        patch.object(svc.pipeline_cover_letters, "generate_draft", new=generate),
    ):
        result = await svc.regenerate_stale_covers("u1")

    assert result["matched_stale"] == 2
    assert result["regenerated"] == 1
    assert result["errors"] == [{"pipeline_id": "p2", "error": "llm error"}]
    assert generate.await_count == 2


@pytest.mark.asyncio
async def test_maintenance_api_lock_rejects_parallel_action():
    from app.api import vacancies as api

    lock = asyncio.Lock()
    await lock.acquire()
    api._maintenance_locks["u1"] = lock
    try:
        with pytest.raises(HTTPException) as ex:
            await api._run_maintenance_locked("u1", AsyncMock())
    finally:
        lock.release()
        api._maintenance_locks.pop("u1", None)

    assert ex.value.status_code == 409
    assert "already in progress" in str(ex.value.detail)
