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
