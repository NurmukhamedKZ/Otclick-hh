from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_approve_binds_hash_to_exact_draft_text():
    from app.services import send_queue_service as svc

    draft = "Точный текст сопроводительного письма"
    approved = {
        "id": "p1",
        "status": "approved",
        "cover_letter_draft": draft,
        "approved_letter_hash": svc.letter_hash(draft),
    }
    with (
        patch.object(
            svc.vacancy_review_service,
            "get_vacancy",
            new=AsyncMock(side_effect=[{"id": "p1", "status": "letter_draft", "cover_letter_draft": draft}, approved]),
        ),
        patch.object(svc.vacancy_pipeline, "transition", return_value=True) as transition,
    ):
        row = await svc.approve_letter("u1", "p1")

    assert row["status"] == "approved"
    changes = transition.call_args.kwargs["changes"]
    assert changes["approved_letter_hash"] == svc.letter_hash(draft)
    assert len(changes["approved_letter_hash"]) == 64


@pytest.mark.asyncio
async def test_queue_rejects_draft_changed_after_approval():
    from app.services import send_queue_service as svc

    vacancy = {
        "id": "p1",
        "status": "approved",
        "resume_id": "r1",
        "hh_vacancy_id": "123",
        "cover_letter_draft": "changed text",
        "approved_letter_hash": svc.letter_hash("approved text"),
    }
    with (
        patch.object(svc.vacancy_review_service, "get_vacancy", new=AsyncMock(return_value=vacancy)),
        patch.object(svc, "_queue_row", return_value=None),
    ):
        with pytest.raises(HTTPException) as ex:
            await svc.queue_approved("u1", "p1")

    assert ex.value.status_code == 409
    assert "approve exact text again" in str(ex.value.detail)


@pytest.mark.asyncio
async def test_queue_is_idempotent_for_already_queued_vacancy():
    from app.services import send_queue_service as svc

    job = {
        "id": "q1",
        "vacancy_pipeline_id": "p1",
        "status": "queued",
        "hh_vacancy_id": "123",
        "approved_letter_hash": "a" * 64,
    }
    with (
        patch.object(
            svc.vacancy_review_service,
            "get_vacancy",
            new=AsyncMock(return_value={"id": "p1", "status": "queued_to_send"}),
        ),
        patch.object(svc, "_queue_row", return_value=job),
    ):
        result = await svc.queue_approved("u1", "p1")

    assert result is job


@pytest.mark.asyncio
async def test_edit_after_approval_returns_to_draft_and_clears_hash():
    from app.services import pipeline_cover_letters as svc

    initial = {
        "id": "p1",
        "status": "approved",
        "cover_letter_draft": "old",
        "cover_letter_meta": {"fact_keys": ["f1"], "edited_by_user": False},
    }
    after = {
        **initial,
        "status": "letter_draft",
        "cover_letter_draft": "new",
        "approved_letter_hash": None,
        "approved_at": None,
    }
    with (
        patch.object(
            svc.vacancy_review_service,
            "get_vacancy",
            new=AsyncMock(side_effect=[initial, after]),
        ),
        patch.object(svc, "_active_send_job", return_value=None),
        patch.object(svc.vacancy_pipeline, "transition", return_value=True) as transition,
    ):
        row = await svc.save_draft("u1", "p1", "new")

    assert row["status"] == "letter_draft"
    call = transition.call_args.kwargs
    assert call["from_statuses"] == ["approved"]
    assert call["to_status"] == "letter_draft"
    assert call["changes"]["approved_letter_hash"] is None
    assert call["changes"]["approved_at"] is None
    assert call["changes"]["cover_letter_meta"]["edited_by_user"] is True


@pytest.mark.asyncio
async def test_edit_is_blocked_once_send_job_is_active():
    from app.services import pipeline_cover_letters as svc

    with (
        patch.object(
            svc.vacancy_review_service,
            "get_vacancy",
            new=AsyncMock(return_value={
                "id": "p1",
                "status": "approved",
                "cover_letter_draft": "old",
                "cover_letter_meta": {},
            }),
        ),
        patch.object(svc, "_active_send_job", return_value={"id": "q1", "status": "queued"}),
    ):
        with pytest.raises(HTTPException) as ex:
            await svc.save_draft("u1", "p1", "new")

    assert ex.value.status_code == 409
    assert "cannot be edited" in str(ex.value.detail)
