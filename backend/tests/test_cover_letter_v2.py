import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")


def test_rich_cover_letter_prompt_has_target_structure():
    from app.ai.cover_letter_prompt import build_cover_letter_prompt

    prompt = build_cover_letter_prompt(mode="balanced")

    assert "Добрый день!" in prompt
    assert "Меня заинтересовала ваша вакансия" in prompt
    assert "Более 20 лет работаю на стыке бизнеса и технологий" in prompt
    assert "Более 12 лет развивал продажи" in prompt
    assert "Наиболее релевантные результаты:" in prompt
    assert "4–6" in prompt
    assert "Готов обсудить, как" in prompt
    assert "Не выдумывай факты" in prompt
    assert "2–3 коротких предложения" not in prompt


def _cache_client(row: dict | None):
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.maybe_single.return_value = chain
    chain.execute.return_value = SimpleNamespace(data=row)

    sb = MagicMock()
    sb.table.return_value = chain
    return sb


def test_cache_rejects_legacy_prompt_version():
    from app.services import cover_letter as cl

    sb = _cache_client({"text": "OLD SHORT LETTER", "prompt_version": "v1"})
    with patch.object(cl, "service_client", sb):
        assert cl._cache_get("v1", "resume-1") is None


def test_cache_accepts_current_prompt_version():
    from app.services import cover_letter as cl

    sb = _cache_client(
        {"text": "RICH LETTER", "prompt_version": cl.COVER_LETTER_PROMPT_VERSION}
    )
    with patch.object(cl, "service_client", sb):
        assert cl._cache_get("v1", "resume-1") == "RICH LETTER"
