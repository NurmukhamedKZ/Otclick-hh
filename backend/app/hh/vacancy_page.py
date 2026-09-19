"""Read a full HH vacancy over the authenticated web session.

HH's shortVacancy state is useful for identity/status but does not contain the
full job text. The rendered applicant vacancy page exposes the description in
`data-qa="vacancy-description"`; this module extracts it without Browser/
Playwright and without OAuth Bearer tokens.
"""

from __future__ import annotations

import asyncio
import re
from html.parser import HTMLParser

from app.hh.page_json import find_state
from app.hh.web import WEB_BASE, _get, _normalise_vacancy
from app.services.form_filler import load_web_session

_BLOCK_TAGS = frozenset({"br", "div", "p", "li", "ul", "ol", "h1", "h2", "h3", "h4"})
_VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})


class _DescriptionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts: list[str] = []

    @staticmethod
    def _is_target(attrs: list[tuple[str, str | None]]) -> bool:
        return any(key == "data-qa" and value == "vacancy-description" for key, value in attrs)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.depth == 0:
            if self._is_target(attrs):
                self.depth = 1
            return
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag not in _VOID_TAGS:
            self.depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.depth and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.depth == 0:
            return
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag not in _VOID_TAGS:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.parts.append(data)


def extract_description(page_html: str) -> str:
    parser = _DescriptionParser()
    parser.feed(page_html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n+ *", "\n", text)
    return text.strip()


async def get_full_vacancy(user_id: str, vacancy_id: str) -> dict:
    """Return normalized vacancy + full description + applicant response state."""
    loop = asyncio.get_running_loop()
    session = await load_web_session(user_id)
    url = f"{WEB_BASE}/vacancy/{vacancy_id}"
    resp = await loop.run_in_executor(None, _get, session, user_id, url)

    short = find_state(resp.text, "shortVacancy")
    vacancy = _normalise_vacancy(short)
    vacancy["description"] = extract_description(resp.text)

    try:
        status = find_state(resp.text, "applicantVacancyResponseStatuses").get(str(vacancy_id)) or {}
    except ValueError:
        status = {}
    if isinstance(status.get("test"), dict):
        vacancy["has_test"] = bool(status["test"].get("hasTests"))
    topics = (status.get("negotiations") or {}).get("topicList") or []
    vacancy["already_responded"] = bool(topics)
    return vacancy
