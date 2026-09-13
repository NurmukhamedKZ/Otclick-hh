from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_bulk_queue_deduplicates_and_keeps_individual_errors():
    from app.services import bulk_send_queue as svc

    queue = AsyncMock(
        side_effect=[
            {"id": "q1"},
            HTTPException(status_code=409, detail="only an approved vacancy can be queued"),
        ]
    )
    with patch.object(svc.send_queue_service, "queue_approved", new=queue):
        result = await svc.queue_many("u1", ["p1", "p1", "p2"])

    assert [item["pipeline_id"] for item in result["results"]] == ["p1", "p2"]
    assert result["queued"] == 1
    assert result["errors"] == 1
    assert result["results"][0]["job_id"] == "q1"
    assert "approved vacancy" in result["results"][1]["error"]
    assert queue.await_count == 2


@pytest.mark.asyncio
async def test_bulk_queue_never_calls_any_approval_helper():
    from app.services import bulk_send_queue as svc

    with (
        patch.object(svc.send_queue_service, "queue_approved", new=AsyncMock(return_value={"id": "q1"})) as queue,
        patch.object(svc.send_queue_service, "approve_letter", new=AsyncMock()) as approve,
    ):
        result = await svc.queue_many("u1", ["p1"])

    assert result["queued"] == 1
    queue.assert_awaited_once_with("u1", "p1")
    approve.assert_not_awaited()
