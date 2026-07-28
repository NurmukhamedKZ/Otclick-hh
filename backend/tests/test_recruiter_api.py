import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.api.deps import get_current_user
    from app.main import app
    app.dependency_overrides[get_current_user] = lambda: "u1"
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_drafts(client):
    with patch("app.api.recruiter.recruiter.list_drafts", new=AsyncMock(return_value=[{"id": "d1"}])):
        r = client.get("/api/recruiter/drafts")
    assert r.status_code == 200
    assert r.json()[0]["id"] == "d1"


def test_send_draft(client):
    with patch("app.api.recruiter.recruiter.send_draft", new=AsyncMock()) as send:
        r = client.post("/api/recruiter/drafts/d1/send", json={"message": "edited"})
    assert r.status_code == 200
    send.assert_awaited_once_with("u1", "d1", message="edited")


def test_discard_draft(client):
    with patch("app.api.recruiter.recruiter.discard_draft", new=AsyncMock()) as disc:
        r = client.post("/api/recruiter/drafts/d1/discard")
    assert r.status_code == 200
    disc.assert_awaited_once_with("u1", "d1")


def test_list_todos(client):
    with patch("app.api.recruiter.recruiter.list_todos", new=AsyncMock(return_value=[{"id": "t1"}])):
        r = client.get("/api/recruiter/todos")
    assert r.status_code == 200
    assert r.json()[0]["id"] == "t1"


def test_todo_done(client):
    with patch("app.api.recruiter.recruiter.mark_todo", new=AsyncMock()) as mt:
        r = client.post("/api/recruiter/todos/t1/done")
    assert r.status_code == 200
    mt.assert_awaited_once_with("u1", "t1", "done")
