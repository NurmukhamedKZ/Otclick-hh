"""Positioning-mode coverage for app/ai/prompts.py — see docs/spec-ai-positioning.md."""

import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")


# --- recruiter chat -----------------------------------------------------------

def test_recruiter_balanced_has_no_social_proof_tactics():
    from app.ai.prompts import build_recruiter_rules

    p = build_recruiter_rules(mode="balanced")
    assert "финальных этапах" not in p
    assert "НИКОГДА не выдумывай опыт" in p


def test_recruiter_full_adds_social_proof_but_still_bans_fact_rewrite():
    from app.ai.prompts import build_recruiter_rules

    p = build_recruiter_rules(mode="full")
    assert "финальных этапах" in p
    assert "НИКОГДА не переписывай факты резюме" in p


def test_recruiter_default_mode_reads_settings(monkeypatch):
    from app.ai.prompts import build_recruiter_rules
    from app.config import settings

    monkeypatch.setattr(settings, "AI_POSITIONING", "full")
    assert build_recruiter_rules() == build_recruiter_rules(mode="full")


def test_build_recruiter_prompt_embeds_resume_and_tools():
    from app.ai.prompts import build_recruiter_prompt

    p = build_recruiter_prompt("Python dev, 3 года опыта", mode="balanced")
    assert "Python dev, 3 года опыта" in p
    assert "answer_recruiter_question" in p
    assert "escalate_to_human" in p
    assert "make_todo" in p


# --- vacancy-test free-text answers -------------------------------------------

def test_form_text_balanced_has_no_experience_padding():
    from app.ai.prompts import build_form_text_prompt

    p = build_form_text_prompt("Сколько лет опыта?", "Junior, 1 год", mode="balanced")
    assert "3-4 года" not in p
    assert "рыночный минимум" not in p


def test_form_text_full_adds_experience_and_salary_padding():
    from app.ai.prompts import build_form_text_prompt

    p = build_form_text_prompt("Сколько лет опыта?", "Junior, 1 год", mode="full")
    assert "3-4 года" in p
    assert "рыночный минимум" in p


def test_form_text_story_instructions_present_in_both_modes():
    from app.ai.prompts import build_form_text_prompt

    for mode in ("balanced", "full"):
        p = build_form_text_prompt("Расскажите о сложном проекте", "ctx", mode=mode)
        assert "STAR" in p
        assert "не сухим канцеляритом" in p


# --- vacancy-test multiple-choice answers -------------------------------------

def test_form_choice_balanced_has_no_dumping_guard():
    from app.ai.prompts import build_form_choice_prompt

    p = build_form_choice_prompt("Опыт?", "1: 1 год\n2: 3 года", "ctx", mode="balanced")
    assert "не занижает кандидата" not in p


def test_form_choice_full_adds_dumping_guard():
    from app.ai.prompts import build_form_choice_prompt

    p = build_form_choice_prompt("Опыт?", "1: 1 год\n2: 3 года", "ctx", mode="full")
    assert "не занижает кандидата" in p
    assert "1: 1 год" in p  # options block still embedded verbatim


# --- cover letter ---------------------------------------------------------------

def test_cover_letter_balanced_has_no_desperate_tone_guard():
    from app.ai.prompts import build_cover_letter_prompt

    p = build_cover_letter_prompt(mode="balanced")
    assert "отчаянного тона" not in p
    assert "Не выдумывай факты" in p


def test_cover_letter_full_adds_salary_and_tone_guidance():
    from app.ai.prompts import build_cover_letter_prompt

    p = build_cover_letter_prompt(mode="full")
    assert "отчаянного тона" in p
    assert "Не выдумывай факты" in p


# --- extension autofill -----------------------------------------------------

def test_fill_balanced_forbids_positioning_optional_fields():
    from app.ai.prompts import build_fill_system_prompt

    p = build_fill_system_prompt(mode="balanced")
    assert "позиционировать кандидата выгоднее" not in p
    assert "Ничего не выдумывай" in p


def test_fill_full_allows_positioning_optional_fields_never_contacts():
    from app.ai.prompts import build_fill_system_prompt

    p = build_fill_system_prompt(mode="full")
    assert "позиционировать кандидата выгоднее" in p
    assert "никогда не выдумывай" in p  # contact/personal fields guard stays


# --- extension chat ------------------------------------------------------------

def test_chat_balanced_has_no_negotiation_tactics_hint():
    from app.ai.prompts import build_chat_system_prompt

    p = build_chat_system_prompt(mode="balanced")
    assert "тактику позиционирования" not in p


def test_chat_full_offers_negotiation_tactics_hint():
    from app.ai.prompts import build_chat_system_prompt

    p = build_chat_system_prompt(mode="full")
    assert "тактику позиционирования" in p


def test_build_chat_prompt_forwards_mode_and_keeps_context():
    from app.ai.prompts import build_chat_prompt

    p = build_chat_prompt("резюме кандидата", page_text="текст вакансии", mode="full")
    assert "тактику позиционирования" in p
    assert "резюме кандидата" in p
    assert "текст вакансии" in p
