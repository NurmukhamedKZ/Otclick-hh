from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_reject_requires_reason():
    from app.services import vacancy_review_service as svc

    with pytest.raises(HTTPException) as exc:
        await svc.decide("u1", "p1", action="reject", reason=None)

    assert exc.value.status_code == 400
    assert "reason" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_review_action_cannot_move_sending_vacancy():
    from app.services import vacancy_review_service as svc

    with patch.object(svc, "_get_owned", return_value={"id": "p1", "status": "sending"}):
        with pytest.raises(HTTPException) as exc:
            await svc.decide("u1", "p1", action="hold", reason="проверить позже")

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_select_uses_conditional_transition_and_clears_old_reason():
    from app.services import vacancy_review_service as svc

    current = {"id": "p1", "status": "review"}
    final = {"id": "p1", "status": "selected", "sources": []}

    with (
        patch.object(svc, "_get_owned", return_value=current),
        patch.object(svc.vacancy_pipeline, "transition", return_value=True) as transition,
        patch.object(svc, "get_vacancy", new=AsyncMock(return_value=final)),
    ):
        row = await svc.decide("u1", "p1", action="select", reason=None)

    assert row["status"] == "selected"
    kwargs = transition.call_args.kwargs
    assert kwargs["from_statuses"] == ["review"]
    assert kwargs["to_status"] == "selected"
    assert kwargs["changes"]["user_decision_reason"] is None


@pytest.mark.asyncio
async def test_reject_persists_user_reason():
    from app.services import vacancy_review_service as svc

    current = {"id": "p1", "status": "review"}
    final = {"id": "p1", "status": "rejected_by_user", "sources": []}

    with (
        patch.object(svc, "_get_owned", return_value=current),
        patch.object(svc.vacancy_pipeline, "transition", return_value=True) as transition,
        patch.object(svc, "get_vacancy", new=AsyncMock(return_value=final)),
    ):
        await svc.decide("u1", "p1", action="reject", reason="слишком операционная роль")

    assert transition.call_args.kwargs["changes"]["user_decision_reason"] == "слишком операционная роль"
