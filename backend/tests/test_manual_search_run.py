from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

RUN = {
    "id": "run-1",
    "user_id": "u1",
    "status": "queued",
    "discovery": None,
    "scoring": None,
    "error": None,
    "created_at": None,
    "started_at": None,
    "finished_at": None,
    "updated_at": None,
}


@pytest.mark.asyncio
async def test_manual_run_only_enqueues_and_returns_immediately():
    from app.api import search_sources as api

    with patch.object(
        api.search_run_service,
        "enqueue",
        new=AsyncMock(return_value=(RUN, True)),
    ) as enqueue:
        result = await api.run_now("u1")

    assert result.id == "run-1"
    assert result.status == "queued"
    assert result.discovery is None
    assert result.scoring is None
    enqueue.assert_awaited_once_with("u1")


@pytest.mark.asyncio
async def test_second_click_returns_existing_active_run_idempotently():
    from app.api import search_sources as api

    running = {**RUN, "status": "scoring"}
    with patch.object(
        api.search_run_service,
        "enqueue",
        new=AsyncMock(return_value=(running, False)),
    ):
        result = await api.run_now("u1")

    assert result.id == "run-1"
    assert result.status == "scoring"


@pytest.mark.asyncio
async def test_manual_run_status_is_user_scoped():
    from app.api import search_sources as api

    completed = {
        **RUN,
        "status": "completed",
        "discovery": {"sources": 1, "fetched": 2, "persisted": 2, "errors": 0},
        "scoring": {"found": 2, "scored": 2, "errors": 0},
    }
    with patch.object(
        api.search_run_service,
        "get_owned",
        new=AsyncMock(return_value=completed),
    ) as get_owned:
        result = await api.get_run("run-1", "u1")

    assert result.status == "completed"
    assert result.scoring["scored"] == 2
    get_owned.assert_awaited_once_with("u1", "run-1")


@pytest.mark.asyncio
async def test_manual_run_status_propagates_not_found():
    from app.api import search_sources as api

    with patch.object(
        api.search_run_service,
        "get_owned",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="search run not found")),
    ):
        with pytest.raises(HTTPException) as ex:
            await api.get_run("other-run", "u1")

    assert ex.value.status_code == 404
