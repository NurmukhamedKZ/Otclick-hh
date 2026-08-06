"""Recon: capture the inline JSON of every hh page the web path will need.

Reuses the live web session stored during OAuth login (no re-login):

    cd backend && python scripts/recon_web.py <user_id> <vacancy_id>

Dumps backend/recon_web_out/*.{html,json}. The markers are guesses — when
one is not found the script prints MARKER NOT FOUND and dumps the HTML; find
the real key in the dump and correct the table.
"""

from __future__ import annotations

import asyncio
import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._local_env import use_public_supabase_url  # noqa: E402

use_public_supabase_url()

from app.hh.page_json import find_balanced_object, find_state  # noqa: E402
from app.services.form_filler import load_web_session  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "recon_web_out"

PAGES = {
    "resumes": ("https://hh.ru/applicant/resumes", '"applicantResumes"'),
    "negotiations": ("https://hh.ru/applicant/negotiations", '"applicantNegotiations"'),
    "vacancy": ("https://hh.ru/vacancy/{vacancy_id}", '"vacancyView"'),
}


def dump(session, name, url, marker):
    r = session.get(url, timeout=20)
    text = html.unescape(r.text)
    if "/account/login" in (r.url or ""):
        print(f"{name}: LOGIN WALL — the stored web session is dead, reconnect first")
        return text
    OUT.joinpath(f"{name}.html").write_text(text, encoding="utf-8")
    i = text.find(marker)
    if i == -1:
        print(
            f"{name}: MARKER {marker} NOT FOUND (status={r.status_code}) — "
            f"open {name}.html and find the real key"
        )
        return text
    blob = find_balanced_object(text, text.find("{", i))
    OUT.joinpath(f"{name}.json").write_text(blob, encoding="utf-8")
    print(f"{name}: ok, {len(blob)} bytes -> {name}.json")
    return text


async def main() -> None:
    OUT.mkdir(exist_ok=True)
    user_id = sys.argv[1]
    vacancy_id = sys.argv[2] if len(sys.argv) > 2 else ""
    session = await load_web_session(user_id)
    for name, (url, marker) in PAGES.items():
        if "{vacancy_id}" in url and not vacancy_id:
            continue  # no vacancy to capture yet
        url = url.format(vacancy_id=vacancy_id)
        text = dump(session, name, url, marker)
        # The full resume (experience/education) is NOT on the list page; it
        # lives on the detail page, whose hash we can only learn from the list.
        if name == "resumes" and text:
            for r in find_state(text, "applicantResumes") or []:
                h = (r.get("_attributes") or {}).get("hash")
                if h:
                    dump(session, "resume_detail",
                         f"https://hh.ru/resume/{h}", '"resume"')
                    break


if __name__ == "__main__":
    asyncio.run(main())
