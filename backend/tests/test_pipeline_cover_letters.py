from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def _rich_result(*, fact_keys: list[str] | None = None):
    from app.services.pipeline_cover_letters import CoverDraftResult

    return CoverDraftResult(
        language="ru",
        greeting="Добрый день!",
        opening=(
            "Меня заинтересовала ваша вакансия как роль с реальным мандатом на изменение бизнес-процессов и ИТ-функции. "
            "В моём опыте близкие задачи решались через управляемое масштабирование, архитектуру и прозрачные метрики результата."
        ),
        profile=(
            "Более 20 лет работаю на стыке бизнеса и технологий. На последних управленческих ролях отвечал за развитие ИТ, "
            "надежность критичных систем и запуск изменений одновременно с ростом бизнеса, сохраняя управляемость функции и команды."
        ),
        achievements=[
            "Поддержал кратный рост бизнеса, масштабируя критичные системы и процессы без пропорционального роста ИТ-функции и сохраняя стабильность операций.",
            "Выстроил круглосуточную поддержку критичных сервисов с разделением L1/L2/L3, управляемой эскалацией и контролем инцидентов.",
            "Запускал WMS на нескольких складских площадках параллельно, связывая технологические изменения с операционными требованиями бизнеса.",
            "Внедрил стандартизированный мониторинг и SLO/SLI для критичных контуров, сократив шум уведомлений и ускорив локализацию проблем.",
            "Развивал интеграционную архитектуру и единый подход к данным и сервисам, чтобы новые проекты запускались быстрее и предсказуемее.",
        ],
        bridge=(
            "Поэтому в этой роли могу быть полезен там, где требуется одновременно удерживать надежность текущего контура и проводить трансформацию, "
            "связывая архитектурные решения, команду и приоритеты с измеримыми задачами бизнеса."
        ),
        cta="Готов обсудить, как выстроить приоритеты трансформации и обеспечить их реализацию без потери устойчивости текущих операций.",
        signature="С уважением, Дмитрий Губернатчук",
        fact_keys=fact_keys or ["fact-1", "fact-2", "fact-3"],
    )


def test_structured_rich_draft_has_required_blocks_and_length():
    from app.services.pipeline_cover_letters import _assemble_draft, _validate_draft

    text = _assemble_draft(_rich_result())
    assert text.startswith("Добрый день!")
    assert "Наиболее релевантные результаты:" in text
    assert sum(1 for line in text.splitlines() if line.startswith("- ")) == 5
    assert "Готов обсудить" in text
    assert _validate_draft(text, {"fact-1", "fact-2", "fact-3"}) == text


def test_generated_draft_rejects_short_text():
    from app.services.pipeline_cover_letters import _validate_draft

    with pytest.raises(ValueError, match="outside_1400_3500"):
        _validate_draft("Короткий текст", {"fact-1", "fact-2"})


def test_generated_draft_requires_results_block():
    from app.services.pipeline_cover_letters import _validate_draft

    text = ("Подтверждённый управленческий опыт и релевантный бизнес-результат. " * 30)[:1800]
    with pytest.raises(ValueError, match="missing_results_block"):
        _validate_draft(text, {"fact-1", "fact-2"})


@pytest.mark.asyncio
async def test_llm_failure_does_not_create_fallback_draft():
    from app.services import pipeline_cover_letters as svc

    vacancy = {
        "id": "p1",
        "status": "selected",
        "resume_id": "r1",
        "title": "CIO",
        "employer_name": "Example",
        "description": "Нужен CIO для цифровой трансформации.",
        "score_details": {},
        "score_explanation": None,
    }
    context = {
        "version": 1,
        "profile": {},
        "facts": [
            {"fact_key": "fact-1", "statement": "Подтверждённый факт"},
            {"fact_key": "fact-2", "statement": "Второй подтверждённый факт"},
        ],
    }
    fake_agent = MagicMock()
    fake_agent.llm = object()

    with (
        patch.object(svc.vacancy_review_service, "get_vacancy", new=AsyncMock(return_value=vacancy)),
        patch.object(svc, "_resolve_resume_row", return_value={"id": "r1", "hh_resume_id": "hh-r1"}),
        patch.object(svc, "load_resume", new=AsyncMock(return_value={"title": "CIO"})),
        patch.object(svc, "_resume_summary", return_value="Желаемая должность: CIO"),
        patch.object(svc.candidate_context_service, "load_candidate_context", new=AsyncMock(return_value=context)),
        patch.object(svc, "HHAgent", return_value=fake_agent),
        patch.object(svc, "_generate_with_llm", new=AsyncMock(side_effect=RuntimeError("model unavailable"))),
        patch.object(svc.vacancy_pipeline, "transition") as transition,
    ):
        with pytest.raises(RuntimeError, match="model unavailable"):
            await svc.generate_draft("u1", "p1")

    transition.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_fact_key_is_not_persisted_as_draft():
    from app.services import pipeline_cover_letters as svc

    vacancy = {
        "id": "p1",
        "status": "selected",
        "resume_id": "r1",
        "title": "CIO",
        "employer_name": "Example",
        "description": "Нужен CIO для цифровой трансформации.",
        "score_details": {},
        "score_explanation": None,
    }
    context = {
        "version": 1,
        "profile": {},
        "facts": [
            {"fact_key": "known", "statement": "Подтверждённый факт"},
            {"fact_key": "known-2", "statement": "Ещё один подтверждённый факт"},
        ],
    }
    result = _rich_result(fact_keys=["known", "invented"])
    fake_agent = MagicMock()
    fake_agent.llm = object()

    with (
        patch.object(svc.vacancy_review_service, "get_vacancy", new=AsyncMock(return_value=vacancy)),
        patch.object(svc, "_resolve_resume_row", return_value={"id": "r1", "hh_resume_id": "hh-r1"}),
        patch.object(svc, "load_resume", new=AsyncMock(return_value={"title": "CIO"})),
        patch.object(svc, "_resume_summary", return_value="Желаемая должность: CIO"),
        patch.object(svc.candidate_context_service, "load_candidate_context", new=AsyncMock(return_value=context)),
        patch.object(svc, "HHAgent", return_value=fake_agent),
        patch.object(svc, "_generate_with_llm", new=AsyncMock(return_value=result)),
        patch.object(svc.vacancy_pipeline, "transition") as transition,
    ):
        with pytest.raises(HTTPException) as exc:
            await svc.generate_draft("u1", "p1")

    assert exc.value.status_code == 502
    transition.assert_not_called()
