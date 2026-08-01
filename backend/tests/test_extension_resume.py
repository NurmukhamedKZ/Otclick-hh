import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

RESUME = {
    "title": "Python-разработчик",
    "download": {"pdf": {"url": "https://api.hh.ru/resumes/x/download/cv.pdf?type=pdf"}},
}


@pytest.mark.asyncio
async def test_fetch_returns_bytes_and_filename():
    from app.services import extension_resume

    resp = MagicMock(status_code=200, content=b"%PDF-1.4 fake")
    client = MagicMock(access_token="tok")
    with (
        patch.object(extension_resume, "load_resume", new=AsyncMock(return_value=RESUME)),
        patch.object(extension_resume, "load_api_client", new=AsyncMock(return_value=client)),
        patch.object(extension_resume.requests, "get", return_value=resp) as get,
    ):
        out = await extension_resume.fetch_resume_pdf("u1")
    assert out == (b"%PDF-1.4 fake", "cv.pdf")
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"


@pytest.mark.asyncio
async def test_fetch_returns_none_without_download_link():
    from app.services import extension_resume

    with patch.object(extension_resume, "load_resume", new=AsyncMock(return_value={"title": "x"})):
        assert await extension_resume.fetch_resume_pdf("u1") is None


@pytest.mark.asyncio
async def test_fetch_returns_none_on_http_error():
    from app.services import extension_resume

    resp = MagicMock(status_code=403, content=b"")
    with (
        patch.object(extension_resume, "load_resume", new=AsyncMock(return_value=RESUME)),
        patch.object(
            extension_resume,
            "load_api_client",
            new=AsyncMock(return_value=MagicMock(access_token="t")),
        ),
        patch.object(extension_resume.requests, "get", return_value=resp),
    ):
        assert await extension_resume.fetch_resume_pdf("u1") is None


@pytest.mark.asyncio
async def test_fetch_returns_none_when_resume_load_fails():
    from app.services import extension_resume

    with patch.object(
        extension_resume, "load_resume", new=AsyncMock(side_effect=RuntimeError("hh down"))
    ):
        assert await extension_resume.fetch_resume_pdf("u1") is None


@pytest.mark.asyncio
async def test_fetch_decodes_percent_encoded_filename():
    """hh puts the candidate's name in the URL, percent-encoded and non-ASCII."""
    from app.services import extension_resume

    resume = {
        "download": {
            "pdf": {"url": "https://api.hh.ru/resumes/x/download/%D0%98%D0%B2%D0%B0%D0%BD.pdf?type=pdf"}
        }
    }
    resp = MagicMock(status_code=200, content=b"%PDF")
    with (
        patch.object(extension_resume, "load_resume", new=AsyncMock(return_value=resume)),
        patch.object(
            extension_resume,
            "load_api_client",
            new=AsyncMock(return_value=MagicMock(access_token="t")),
        ),
        patch.object(extension_resume.requests, "get", return_value=resp),
    ):
        out = await extension_resume.fetch_resume_pdf("u1")
    assert out is not None and out[1] == "Иван.pdf"
