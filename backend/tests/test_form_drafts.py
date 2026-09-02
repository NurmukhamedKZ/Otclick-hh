import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

DRAFT = {
    "id": "d1",
    "user_id": "u1",
    "resume_id": "r1",
    "vacancy_id": "v1",
    "answers": [{"task_id": "t1", "question": "Q?", "answer": "AI answer"}],
    "letter": "",
    "status": "pending",
}

UPserts = list  # noqa: N816


@pytest.fixture
def upserts():
    calls: UPserts = []

    async def _rec(user_id, question, answer, source="manual", vacancy_id=None):
        calls.append((question, answer, source))
        return {}

    with patch("app.services.qa_memory.upsert", side_effect=_rec):
        yield calls


@pytest.mark.asyncio
async def test_failed_submit_does_not_touch_qa_memory(upserts):
    from app.services import form_drafts

    with patch.object(form_drafts, "_get", new=AsyncMock(return_value=dict(DRAFT))), \
         patch.object(form_drafts, "_update", new=AsyncMock()) as upd, \
         patch("app.services.form_filler.submit_prepared_form",
               new=AsyncMock(return_value=("failed", "captcha"))):
        status, error = await form_drafts.approve("u1", "d1", answers=[
            {"task_id": "t1", "question": "Q?", "answer": "USER edit"},
        ])
    assert (status, error) == ("failed", "captcha")
    assert upserts == []  # audit #18: nothing persisted before a successful send
    patch_status = upd.call_args[0][1]["status"]
    assert patch_status == "failed"


@pytest.mark.asyncio
async def test_successful_submit_persists_all_answers(upserts):
    from app.services import form_drafts

    with patch.object(form_drafts, "_get", new=AsyncMock(return_value=dict(DRAFT))), \
         patch.object(form_drafts, "_update", new=AsyncMock()), \
         patch.object(form_drafts, "_mirror_application", new=AsyncMock()), \
         patch("app.services.form_filler.submit_prepared_form",
               new=AsyncMock(return_value=("form_sent", None))):
        status, _ = await form_drafts.approve("u1", "d1", answers=[
            {"task_id": "t1", "question": "Q?", "answer": "USER edit"},
        ])
    assert status == "form_sent"
    assert upserts == [("Q?", "USER edit", "form")]
