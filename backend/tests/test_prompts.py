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
