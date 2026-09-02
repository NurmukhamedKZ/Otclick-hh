"""Pydantic-validated LLM answers with a plain-JSON fallback.

Some OpenAI-compatible proxies (e.g. deepseek) reject `response_format` of
type json_schema with 400 "This response_format type is unavailable now".
So: try `with_structured_output` first (strict schema), and on any failure
repeat as a plain completion and parse the JSON out of the text — every
prompt that reaches this module already demands bare JSON in the reply.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> Any:
    """Parse the first {...} block found in the model's reply."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in model output")
    return json.loads(match.group(0))


def _content_text(resp: Any) -> str:
    content = getattr(resp, "content", None)
    return content if isinstance(content, str) else str(content)


def structured_call_sync(llm, model_cls: type[BaseModel], prompt: Any) -> BaseModel:
    try:
        out = llm.with_structured_output(model_cls).invoke(prompt)
        return out if isinstance(out, model_cls) else model_cls.model_validate(out)
    except Exception:
        logger.info("llm: structured output unavailable — falling back to json parsing")
    resp = llm.invoke(prompt)
    return model_cls.model_validate(_extract_json(_content_text(resp)))


async def structured_call(llm, model_cls: type[BaseModel], prompt: Any) -> BaseModel:
    try:
        out = await llm.with_structured_output(model_cls).ainvoke(prompt)
        return out if isinstance(out, model_cls) else model_cls.model_validate(out)
    except Exception:
        logger.info("llm: structured output unavailable — falling back to json parsing")
    resp = await llm.ainvoke(prompt)
    return model_cls.model_validate(_extract_json(_content_text(resp)))
