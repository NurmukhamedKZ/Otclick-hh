"""Recon: capture the exact POST to vacancy_response/popup for a NO-TEST vacancy.

Loads the stored web session cookies into a real browser, opens a no-test
vacancy, clicks «Откликнуться» and records the form body + headers of the
`vacancy_response/popup` request. This is the single highest-risk unknown:
the current form_filler._submit always sends uidPk/guid/startTime/testRequired
which only exist when the vacancy HAS a test. We need the real no-test shape.

    cd backend && python scripts/recon_apply.py <vacancy_id>

Only captures; nothing is submitted unless hh requires it to advance past the
response dialog (a plain response, no test → this IS a real apply). Use a
throwaway account/vacancy you don't care about.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._local_env import use_public_supabase_url  # noqa: E402

use_public_supabase_url()

from playwright.async_api import async_playwright  # noqa: E402

from app.services.form_filler import HH_WEB_USER_AGENT, _load_cookies_encrypted  # noqa: E402
from app.services.hh_auth import decrypt_token  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "recon_web_out"
HH_COOKIE_DOMAIN = ".hh.ru"


async def main() -> None:
    OUT.mkdir(exist_ok=True)
    user_id = sys.argv[1]
    vacancy_id = sys.argv[2]

    enc = _load_cookies_encrypted(user_id)
    if not enc:
        raise SystemExit("no stored web session for this user — reconnect required")
    cookies = json.loads(decrypt_token(enc))

    target = f"https://hh.ru/applicant/vacancy_response?vacancyId={vacancy_id}&startedWithQuestion=false&hhtmFrom=vacancy"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=HH_WEB_USER_AGENT)
        for c in cookies:
            try:
                await context.add_cookies([{
                    "name": c["name"], "value": c["value"],
                    "domain": c.get("domain") or HH_COOKIE_DOMAIN,
                    "path": c.get("path", "/"),
                }])
            except Exception:
                pass  # malformed/session-only cookies from the live browser

        page = await context.new_page()

        async def on_request(req):
            if req.url.endswith("/applicant/vacancy_response/popup"):
                body = None
                try:
                    body = req.post_data or ""
                except Exception:
                    pass
                capt = {
                    "method": req.method,
                    "url": req.url,
                    "headers": dict(req.headers),
                    "post_data": body,
                }
                print(f"\n*** POPUP POST CAPTURED\n{json.dumps(capt, indent=2, ensure_ascii=False)}\n")
                (OUT / "apply_no_test.json").write_text(
                    json.dumps(capt, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                print(f"saved -> {OUT / 'apply_no_test.json'}")

        page.on("request", on_request)

        await page.goto(target, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        # The response page may render the submit button; click it if present.
        for sel in [
            'button:has-text("Откликнуться")',
            'button:has-text("ОТКЛИКНУТЬСЯ")',
            '[data-qa="consultation-submit"]',
        ]:
            btn = await page.query_selector(sel)
            if btn:
                await btn.click()
                await page.wait_for_timeout(4000)
                break

        (OUT / "apply.html").write_text(await page.content(), encoding="utf-8")
        print(f"dumped page -> {OUT / 'apply.html'}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())