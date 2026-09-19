from langchain_openai import ChatOpenAI


def test_structured_output_defaults_to_configured_compatible_method(monkeypatch):
    from app.ai import openai_compat

    seen = {}

    def fake_structured(self, schema=None, **kwargs):
        seen["schema"] = schema
        seen.update(kwargs)
        return "wrapped"

    monkeypatch.setattr(
        openai_compat.settings,
        "OPENAI_STRUCTURED_OUTPUT_METHOD",
        "function_calling",
    )
    monkeypatch.setattr(ChatOpenAI, "with_structured_output", fake_structured)

    llm = object.__new__(openai_compat.CompatibleChatOpenAI)
    result = openai_compat.CompatibleChatOpenAI.with_structured_output(
        llm,
        schema=dict,
    )

    assert result == "wrapped"
    assert seen["schema"] is dict
    assert seen["method"] == "function_calling"


def test_explicit_structured_method_is_not_overridden(monkeypatch):
    from app.ai import openai_compat

    seen = {}

    def fake_structured(self, schema=None, **kwargs):
        seen.update(kwargs)
        return "wrapped"

    monkeypatch.setattr(ChatOpenAI, "with_structured_output", fake_structured)
    llm = object.__new__(openai_compat.CompatibleChatOpenAI)
    openai_compat.CompatibleChatOpenAI.with_structured_output(
        llm,
        schema=dict,
        method="json_schema",
    )
    assert seen["method"] == "json_schema"


def test_opencode_headers_use_opaque_stable_session(monkeypatch):
    from app.ai import openai_compat

    monkeypatch.setattr(
        openai_compat.settings,
        "OPENAI_BASE_URL",
        "https://opencode.ai/zen/go/v1",
    )
    first = openai_compat.provider_headers("user-secret-id")
    second = openai_compat.provider_headers("user-secret-id")

    assert first == second
    assert first["User-Agent"] == "otclick-hh/0.1"
    assert first["x-opencode-session"]
    assert "user-secret-id" not in first["x-opencode-session"]


def test_non_opencode_provider_has_no_opencode_session(monkeypatch):
    from app.ai import openai_compat

    monkeypatch.setattr(
        openai_compat.settings,
        "OPENAI_BASE_URL",
        "https://api.longcat.chat/openai/v1",
    )
    headers = openai_compat.provider_headers("u1")
    assert headers == {"User-Agent": "otclick-hh/0.1"}


def test_provider_change_changes_context_fingerprint(monkeypatch):
    from app.services import context_fingerprints

    context = {"version": 1, "profile": {"positioning": "x"}, "facts": []}
    vacancy = {"hh_vacancy_id": "1", "title": "CIO", "description": "transform"}

    monkeypatch.setattr(
        context_fingerprints.settings,
        "OPENAI_BASE_URL",
        "https://opencode.ai/zen/go/v1",
    )
    monkeypatch.setattr(
        context_fingerprints.settings,
        "OPENAI_STRUCTURED_OUTPUT_METHOD",
        "function_calling",
    )
    one = context_fingerprints.score_context(
        context=context,
        rules=[],
        vacancy=vacancy,
        model="longcat-2.0",
    )

    monkeypatch.setattr(
        context_fingerprints.settings,
        "OPENAI_BASE_URL",
        "https://api.longcat.chat/openai/v1",
    )
    two = context_fingerprints.score_context(
        context=context,
        rules=[],
        vacancy=vacancy,
        model="longcat-2.0",
    )

    assert one["context_hash"] != two["context_hash"]
    assert one["provider_base_url"] == "https://opencode.ai/zen/go/v1"
    assert two["provider_base_url"] == "https://api.longcat.chat/openai/v1"
