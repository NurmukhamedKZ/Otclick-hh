"""Compatibility helpers for OpenAI-compatible chat endpoints.

The product uses LangChain's ChatOpenAI protocol surface, but must not depend
on OpenAI-hosted-only structured-output features. Generic providers such as
OpenCode/LongCat commonly implement chat completions + function/tool calling,
so function_calling is the conservative default for structured Pydantic output.
"""

from __future__ import annotations

import hashlib

from langchain_openai import ChatOpenAI

from app.config import settings


class CompatibleChatOpenAI(ChatOpenAI):
    """ChatOpenAI with a configurable provider-compatible structured mode."""

    def with_structured_output(self, schema=None, **kwargs):
        kwargs.setdefault("method", settings.OPENAI_STRUCTURED_OUTPUT_METHOD)
        return super().with_structured_output(schema=schema, **kwargs)


def provider_headers(user_id: str) -> dict[str, str]:
    """Return honest provider headers without pretending to be another client.

    OpenCode Go documents a stable x-opencode-session header. For that endpoint
    we derive an opaque stable id from the local application user id. The raw id
    is never sent. Other providers only receive an explicit Otclick User-Agent.
    """

    headers = {"User-Agent": "otclick-hh/0.1"}
    base = settings.OPENAI_BASE_URL.lower().rstrip("/")
    if "opencode.ai/zen/go" in base:
        digest = hashlib.sha256(f"otclick-hh:{user_id}".encode()).hexdigest()
        headers["x-opencode-session"] = digest[:32]
    return headers
