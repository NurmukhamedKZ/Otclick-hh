#!/usr/bin/env python3
"""Verify the minimal OpenAI-compatible contract Otclick needs.

Checks /chat/completions plus function/tool calling. It intentionally does not
use project dependencies so install.sh can run it before Docker images exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default=".env")
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()

    env = read_env(Path(args.env))
    base = env.get("OPENAI_BASE_URL", "").rstrip("/")
    key = env.get("OPENAI_API_KEY", "")
    model = env.get("OPENAI_MODEL", "")
    if not (base and key and model):
        print("missing OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL", file=sys.stderr)
        return 2

    url = base + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": "Call emit_check exactly once with ok=true. Do not answer in plain text.",
            }
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "emit_check",
                    "description": "Return installer compatibility status.",
                    "parameters": {
                        "type": "object",
                        "properties": {"ok": {"type": "boolean"}},
                        "required": ["ok"],
                        "additionalProperties": False,
                    },
                },
            }
        ],
        "tool_choice": {
            "type": "function",
            "function": {"name": "emit_check"},
        },
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "otclick-hh-installer/0.1",
    }
    if "opencode.ai/zen/go" in base.lower():
        headers["x-opencode-session"] = hashlib.sha256(
            b"otclick-hh-installer-check"
        ).hexdigest()[:32]

    req = Request(
        url,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(req, timeout=args.timeout) as response:
            body = json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        print(f"HTTP {exc.code}: {detail}", file=sys.stderr)
        return 3
    except (URLError, TimeoutError, OSError) as exc:
        print(f"connection failed: {exc}", file=sys.stderr)
        return 4

    try:
        message = body["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        call = calls[0]
        if call.get("function", {}).get("name") != "emit_check":
            raise ValueError("unexpected tool name")
        arguments = call["function"].get("arguments") or "{}"
        parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
        if parsed.get("ok") is not True:
            raise ValueError("tool call did not return ok=true")
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(
            "chat endpoint responded but required function/tool calling was not confirmed: "
            f"{exc}",
            file=sys.stderr,
        )
        return 5

    print(f"verified OpenAI-compatible tool calling: {model} @ {base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
