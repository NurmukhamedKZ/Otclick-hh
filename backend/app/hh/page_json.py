"""hh serves its page state as entity-encoded inline JSON. One parser for all of it."""
from __future__ import annotations

import html
import json


def find_balanced_object(text: str, obj_start: int) -> str:
    """Return the JSON value substring starting at text[obj_start] == '{' or '['.

    Depth-counts both braces and brackets so nested arrays/objects across the
    inline state extract correctly. Originates from services/form_filler.py —
    changes here must keep that module's parse behaviour identical.
    """
    if obj_start >= len(text) or text[obj_start] not in "{[":
        raise ValueError("not at the start of a JSON object/array")
    depth = 0
    in_string = False
    escaped = False
    for i in range(obj_start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return text[obj_start:i + 1]
    raise ValueError("unbalanced JSON value in page")


def find_state(page_html: str, key: str) -> dict:
    """Decode hh's inline page-state and return the value stored under key.

    Reads the marker "<<key>": then walks to the value that follows it, which
    may be an object ({) or an array ([). Entity-unescapes the page only when
    the plain marker is absent, so already-plain pages keep their literal
    &amp; sequences intact. Raises ValueError when key is absent.
    """
    marker = f'"{key}":'
    if marker not in page_html:
        page_html = html.unescape(page_html)
    i = page_html.find(marker)
    if i == -1:
        raise ValueError(f"{key} not found in page")
    start = i + len(marker)
    while start < len(page_html) and page_html[start] in " \t\n\r":
        start += 1
    return json.loads(find_balanced_object(page_html, start), strict=False)