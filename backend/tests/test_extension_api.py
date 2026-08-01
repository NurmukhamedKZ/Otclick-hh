import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

FACTS = {"full_name": "Иван Петров", "email": "ivan@example.com"}


@pytest.fixture
def client():
    from app.api.deps import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: "u1"
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_context_returns_facts(client):
    with (
        patch(
            "app.api.extension.candidate_context.build",
            new=AsyncMock(return_value=("ctx", FACTS)),
        ),
        patch(
            "app.api.extension.extension_resume.fetch_resume_pdf",
            new=AsyncMock(return_value=(b"x", "cv.pdf")),
        ),
    ):
        r = client.get("/api/extension/context")
    assert r.status_code == 200
    assert r.json() == {"facts": FACTS, "has_resume_file": True, "resume_filename": "cv.pdf"}


def test_fill_returns_fields_per_frame(client):
    fields = [
        {
            "ref": "f1",
            "selector": "#a",
            "field_type": "text",
            "value": "Иван Петров",
            "source": "profile",
            "required": True,
        }
    ]
    with (
        patch(
            "app.api.extension.candidate_context.build",
            new=AsyncMock(return_value=("ctx", FACTS)),
        ),
        patch("app.api.extension.HHAgent.fill_form_fields", new=AsyncMock(return_value=fields)),
    ):
        r = client.post(
            "/api/extension/fill",
            json={
                "url": "https://docs.google.com/forms/d/e/x/viewform",
                "page_text": "вакансия",
                "frames": [
                    {
                        "frame_id": 0,
                        "snapshot": [{"ref": "f1", "label": "Имя", "field_type": "text"}],
                    }
                ],
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["frames"][0]["frame_id"] == 0
    assert body["frames"][0]["fields"][0]["frame_id"] == 0
    assert body["frames"][0]["fields"][0]["value"] == "Иван Петров"


def test_fill_rejects_oversized_payload(client):
    huge = [{"ref": f"f{i}", "label": "x", "field_type": "text"} for i in range(501)]
    r = client.post(
        "/api/extension/fill",
        json={"url": "https://x", "page_text": "y", "frames": [{"frame_id": 0, "snapshot": huge}]},
    )
    assert r.status_code == 422


def test_chat_returns_answer(client):
    with (
        patch(
            "app.api.extension.candidate_context.build",
            new=AsyncMock(return_value=("ctx", FACTS)),
        ),
        patch("app.api.extension.HHAgent.chat", new=AsyncMock(return_value="ответ")),
    ):
        r = client.post(
            "/api/extension/chat", json={"messages": [{"role": "user", "content": "привет"}]}
        )
    assert r.status_code == 200
    assert r.json() == {"answer": "ответ"}


def test_qa_saves_items(client):
    with patch("app.api.extension.qa_memory.upsert", new=AsyncMock()) as up:
        r = client.post(
            "/api/extension/qa",
            json={
                "items": [
                    {"question": "Опыт?", "answer": "5 лет"},
                    {"question": " ", "answer": "x"},
                ]
            },
        )
    assert r.status_code == 200
    assert r.json() == {"saved": 1}
    up.assert_awaited_once_with("u1", "Опыт?", "5 лет", source="form")


def test_resume_file_streams_pdf(client):
    with patch(
        "app.api.extension.extension_resume.fetch_resume_pdf",
        new=AsyncMock(return_value=(b"%PDF-1.4", "cv.pdf")),
    ):
        r = client.get("/api/extension/resume-file")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content == b"%PDF-1.4"


def test_resume_file_handles_non_ascii_filename(client):
    """A Cyrillic filename must not blow up the latin-1 header encoding."""
    with patch(
        "app.api.extension.extension_resume.fetch_resume_pdf",
        new=AsyncMock(return_value=(b"%PDF", "Иван.pdf")),
    ):
        r = client.get("/api/extension/resume-file")
    assert r.status_code == 200
    assert "filename*=UTF-8''" in r.headers["content-disposition"]


def test_resume_file_404_when_missing(client):
    with patch(
        "app.api.extension.extension_resume.fetch_resume_pdf", new=AsyncMock(return_value=None)
    ):
        r = client.get("/api/extension/resume-file")
    assert r.status_code == 404
