from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def _query_with(row: dict):
    q = MagicMock()
    for name in ("update", "eq", "select", "maybe_single"):
        getattr(q, name).return_value = q
    q.execute.return_value = SimpleNamespace(data=[row])
    return q


@pytest.mark.asyncio
async def test_reset_failed_returns_pipeline_to_approved_without_retry():
    from app.services import send_queue_service as svc

    text = "approved text"
    digest = svc.letter_hash(text)
    vacancy = {
        "id": "p1",
        "status": "send_error",
        "cover_letter_draft": text,
        "approved_letter_hash": digest,
    }
    job = {
        "id": "q1",
        "status": "failed",
        "approved_letter_hash": digest,
        "last_error": "network_timeout",
    }
    cancelled = {**job, "status": "cancelled", "last_error": "reset_from:failed"}
    q = _query_with(cancelled)

    with (
        patch.object(svc.vacancy_review_service, "get_vacancy", new=AsyncMock(return_value=vacancy)),
        patch.object(svc, "_queue_row", return_value=job),
        patch.object(svc.service_client, "table", return_value=q),
        patch.object(svc.vacancy_pipeline, "transition", return_value=True) as transition,
    ):
        row = await svc.reset_failed("u1", "p1")

    assert row["status"] == "cancelled"
    transition.assert_called_once()
    call = transition.call_args.kwargs
    assert call["from_statuses"] == ["send_error"]
    assert call["to_status"] == "approved"


@pytest.mark.asyncio
async def test_reset_manual_required_has_same_explicit_approval_return_path():
    from app.services import send_queue_service as svc

    text = "approved text"
    digest = svc.letter_hash(text)
    vacancy = {
        "id": "p1",
        "status": "send_error",
        "cover_letter_draft": text,
        "approved_letter_hash": digest,
    }
    job = {
        "id": "q1",
        "status": "manual_required",
        "approved_letter_hash": digest,
        "last_error": "hh_vacancy_has_test",
    }
    q = _query_with({**job, "status": "cancelled"})

    with (
        patch.object(svc.vacancy_review_service, "get_vacancy", new=AsyncMock(return_value=vacancy)),
        patch.object(svc, "_queue_row", return_value=job),
        patch.object(svc.service_client, "table", return_value=q),
        patch.object(svc.vacancy_pipeline, "transition", return_value=True),
    ):
        row = await svc.reset_failed("u1", "p1")

    assert row["status"] == "cancelled"


@pytest.mark.asyncio
async def test_reset_rejects_changed_approved_text():
    from app.services import send_queue_service as svc

    vacancy = {
        "id": "p1",
        "status": "send_error",
        "cover_letter_draft": "changed",
        "approved_letter_hash": svc.letter_hash("approved"),
    }
    job = {
        "id": "q1",
        "status": "failed",
        "approved_letter_hash": svc.letter_hash("approved"),
    }
    with (
        patch.object(svc.vacancy_review_service, "get_vacancy", new=AsyncMock(return_value=vacancy)),
        patch.object(svc, "_queue_row", return_value=job),
    ):
        with pytest.raises(HTTPException) as ex:
            await svc.reset_failed("u1", "p1")

    assert ex.value.status_code == 409
    assert "approved text changed" in str(ex.value.detail)


@pytest.mark.asyncio
async def test_reset_never_accepts_queued_or_sending_job():
    from app.services import send_queue_service as svc

    with (
        patch.object(
            svc.vacancy_review_service,
            "get_vacancy",
            new=AsyncMock(return_value={"id": "p1", "status": "send_error"}),
        ),
        patch.object(svc, "_queue_row", return_value={"id": "q1", "status": "sending"}),
    ):
        with pytest.raises(HTTPException) as ex:
            await svc.reset_failed("u1", "p1")

    assert ex.value.status_code == 409
    assert "not resettable" in str(ex.value.detail)
