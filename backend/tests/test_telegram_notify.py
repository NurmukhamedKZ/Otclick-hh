import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

from app.services.telegram_notify import _format_message, _inline_keyboard  # noqa: E402

BASE = {
    "draft_id": "d1",
    "vacancy_id": "123",
    "vacancy_title": "AI Engineer",
    "employer": "Acme",
}


def test_form_approval_shows_question_answer_pairs():
    msg = _format_message("form_approval", {
        **BASE,
        "answers": [
            {"question": "Готовы ли к командировкам?", "answer": "Да"},
            {"question": "Какой у вас опыт с LLM?", "answer": "3 года"},
        ],
        "letter": "Привет, хочу к вам!",
    })
    assert "https://hh.ru/vacancy/123" in msg
    assert "1. Готовы ли к командировкам?: Да" in msg
    assert "2. Какой у вас опыт с LLM?: 3 года" in msg
    assert "Сопроводительное" in msg and "Привет, хочу к вам!" in msg


def test_form_approval_without_answers_still_renders():
    msg = _format_message("form_approval", dict(BASE))
    assert "AI Engineer" in msg
    assert "Ответы анкеты" not in msg


def test_form_approval_truncates_long_pairs():
    msg = _format_message("form_approval", {
        **BASE,
        "answers": [{"question": "в" * 500, "answer": "о" * 500}],
    })
    assert "в" * 500 not in msg
    assert "о" * 500 not in msg
    assert len(msg) < 4096


def test_form_approval_keyboard_uses_draft_id():
    kb = _inline_keyboard("form_approval", BASE)
    assert kb["inline_keyboard"][0][0]["callback_data"] == "fsend:d1"


def test_recruiter_draft_includes_text():
    msg = _format_message("recruiter_draft", {
        "draft_id": "x1", "draft_text": "Готов обсудить",
        "question_text": "Когда удобно созвониться?", "vacancy_id": "9",
    })
    assert "Когда удобно созвониться?" in msg
    assert "Готов обсудить" in msg
