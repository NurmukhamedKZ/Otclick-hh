"""Recon: what does hh.ru actually send back on the hhandroid:// redirect now?

Opens a REAL browser window on the OAuth authorize URL. You log in by hand
(any method: password, email code, whatever hh shows). The script only watches
and prints every navigation, redirect Location header and any hhandroid:// URL.

    cd backend && python scripts/recon_oauth.py

Nothing is stored, no credentials go through the script.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright  # noqa: E402

from app.hh.client_keys import ANDROID_CLIENT_ID, REDIRECT_URI  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "recon_oauth_out"


async def main() -> None:
    OUT.mkdir(exist_ok=True)
    host = sys.argv[1] if len(sys.argv) > 1 else "hh.ru"
    qs = urlencode({
        "client_id": ANDROID_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
    })
    url = f"https://{host}/oauth/authorize?{qs}"
    print(f"authorize url: {url}\nredirect_uri:  {REDIRECT_URI}\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(**pw.devices["Galaxy A55"])
        page = await context.new_page()

        done = asyncio.Event()

        IGNORED = ("https://", "http://", "blob:", "data:", "chrome-extension://", "about:")

        def on_request(req):
            if req.url.startswith(REDIRECT_URI):
                print(f"\n*** REDIRECT_URI HIT: {req.method} {req.url}\n")
                done.set()
            elif not req.url.startswith(IGNORED):
                print(f"\n*** APP-SCHEME REQUEST: {req.method} {req.url}\n")
                done.set()

        def on_response(resp):
            if host not in resp.url:
                return  # trackers/pixels: pure noise
            loc = resp.headers.get("location")
            if resp.status >= 300 and resp.status < 400:
                print(f"[{resp.status}] {resp.url}\n    -> {loc}")
                if loc and not loc.startswith(("https://", "http://", "/")):
                    print(f"\n*** APP REDIRECT: {loc}\n")
                    done.set()
            elif "/oauth/" in resp.url or "/account/login" in resp.url:
                print(f"[{resp.status}] {resp.url}")

        def on_framenav(frame):
            if frame == page.main_frame:
                print(f"NAV -> {frame.url}")

        page.on("request", on_request)
        page.on("response", on_response)
        page.on("framenavigated", on_framenav)

        await page.goto(url, wait_until="load", timeout=60000)
        print("\n>>> Log in manually in the browser window. Waiting up to 10 min...\n")

        try:
            await asyncio.wait_for(done.wait(), timeout=600)
        except TimeoutError:
            print("\n!!! no app redirect seen within 10 min")

        await asyncio.sleep(2)
        print(f"\nfinal page url: {page.url}")
        (OUT / "page.html").write_text(await page.content(), encoding="utf-8")
        await page.screenshot(path=str(OUT / "page.png"), full_page=True)
        print(f"dumped: {OUT}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
