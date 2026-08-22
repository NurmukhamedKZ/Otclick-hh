# Real captcha solving for the worker's web session — Aug 22

Supersedes the runtime mechanism in `2026-05-25-captcha-handoff-design.md` (that spec's
`captcha_requests`/API/modal plumbing stays; its poll-based "solve" is replaced).

## Problem

hh started captcha-walling this account's stored web session (cookies captured once during
OAuth login, reused by `app/hh/web.py` and `app/services/form_filler.py` for every apply). The
wall shows as a redirect to `https://hh.ru/account/captcha?backurl=...&state=...` serving hh's
own image-captcha widget (`img[data-qa="account-captcha-picture"]` /
`input[data-qa="account-captcha-input"]` — the exact widget `app/hh/authorize.py` already solves
during OAuth login via Playwright).

Two places in `apply.py` currently turn this into `status="captcha"` and pause the runner
(`app/worker/runner.py`, `paused_captcha` state):
1. `web.get_vacancy` (GET `/vacancy/<id>`) — just fixed to raise `web.CaptchaRequired`.
2. `form_filler.submit_response` (POST `/negotiations` path) — detects captcha today via a
   fragile `"captcha" in err_text` substring probe on the POST response, per the existing
   `ponytail:` comment in `apply.py`.

Both currently pause the runner and show a **non-functional** modal ("реши сам на hh") — solving
hh's captcha in the user's own logged-in browser does nothing for the separate cookie jar the
worker holds, so the wall never actually lifts through user action; it only self-clears when hh's
soft rate-limit backs off (observed: seconds to tens of seconds per vacancy, but re-triggers on
the next one — throughput stays near zero).

## Goal

Detect the captcha, pause auto-apply (already true), and let the user actually clear it: see the
real captcha image rendered from the worker's own session, type the answer, submit, and have
auto-apply resume automatically once solved.

Success criteria:
1. Both trigger points detect the captcha via the same URL check and open a real, live browser
   session holding the worker's cookies.
2. The dashboard modal shows the real captcha image (not a "go solve it on hh.ru" message) and a
   text input.
3. Submitting a wrong answer shows hh's next captcha image without leaving the paused state.
4. Submitting the right answer clears the wall, persists the refreshed cookies, and resumes the
   runner within the same request.
5. Multiple users hitting captcha concurrently don't spin unbounded headless Chromium instances.

## Out of scope

- AI auto-solving the captcha image (still just groundwork — a human types the answer).
- The OAuth-login captcha flow (`hh_auth.py`/`authorize.py`) — already works, untouched.
- Any change to how `applications` rows are recorded for `status="captcha"`.

## Correction found while planning

`app` (FastAPI, `uvicorn app.main:app`) and `worker` (`python worker_main.py`) are **separate
containers/processes** (`docker-compose.yml`) with no shared memory — confirmed by the fact
`app/api/*.py` never imports `app.worker.runner` anywhere in the codebase today, and the existing
(currently-dead) `WorkerRegistry.resume_captcha` is only ever exercised by its own unit test, never
by an API route. Sections 3 and 5 below originally assumed `/api/captcha/{id}/solve` could reach
into the worker process's live `RunnerHandle`/`asyncio.Queue` directly — it cannot. Every other
cross-process signal in this codebase (worker flags, worker_runtime heartbeat, the old plan-B
`_probe_me` poll) goes through the database, polled on a timer; the solution handoff follows the
same pattern: `/solve` writes a new `captcha_requests.solution` column, the worker's pause loop
polls for it. Sections below reflect this.

## Decisions (from brainstorming)

- **Mechanism:** Playwright, loaded with the exact cookies `load_web_session` already decrypts —
  not a hand-rolled HTTP reverse-engineering of hh's captcha image endpoint/form target. Reuses
  `authorize.py`'s proven selectors and screenshot→fill→submit sequence.
- **Browser lifecycle:** lives in the worker process's memory for the duration of the pause (one
  Playwright page per captcha-walled user), analogous to `hh_auth.py`'s `captcha_queue` pattern —
  not a fresh open/close per solve attempt (that risks hh rotating the challenge/state token
  between the screenshot the user sees and the answer they submit).
- **Scope:** unify both trigger points behind one detection check and one solving service, rather
  than fixing only the vacancy-fetch path and leaving the POST-submit path on the old fake "go
  solve it yourself" modal.
- **Concurrency:** a global semaphore caps live captcha browsers (default 4, matching
  `hh_auth.MAX_CONCURRENT_JOBS`). Over the cap, the runner stays `paused_captcha` with no browser
  open yet; the modal shows its existing "скриншот грузится…" loading state until a slot frees.

## Architecture

### 1. Detection — extend the existing URL check to the POST path

`app/hh/web.py::CaptchaRequired` exists today but lives in the wrong module for this: it needs to
also be raised from `form_filler._submit_response`, and `web.py` already imports FROM
`form_filler.py` (`WebSessionExpired`, `load_web_session`, `session_looks_dead`) — importing the
other direction would be circular. Move `CaptchaRequired` into `form_filler.py` (next to
`WebSessionExpired`, same reasoning), give it a real `url` attribute instead of a static message
(`raise CaptchaRequired(resp.url)`, not today's placeholder string), and have `web.py` import it
from there instead of defining its own.

Add the matching check to `form_filler._submit_response`'s pre-submit `session.get(page_url)` (the
GET that fetches xsrf/test-meta before posting): if that response's `resp.url` contains
`/account/captcha`, raise `CaptchaRequired(resp.url)` there too.

Keep the existing `"captcha" in err_text` substring check in `apply.py` as a **fallback** only,
for the case where the POST itself (not the preceding GET) is rejected with no page navigation
(no captured real example of this shape — the fallback opens a bare `https://hh.ru/account/captcha`
with no `backurl`/`state`; if the browser finds no captcha widget there, treat it as already
clear and resume immediately).

`apply.py`'s two `except` blocks (GET-vacancy and POST-submit) both catch `CaptchaRequired`,
record the `applications` row with `status="captcha"` (as today), and return `"captcha"` — they do
**not** open a browser themselves. The challenge URL is threaded up via
`captcha_service.create_request(user_id, challenge_url)` (replacing today's `None`) so the runner
has it.

### 2. `app/hh/web_captcha.py` (new) — the solving service

Module-level functions over a process-local session registry (there is exactly one worker
process, so no cross-process concern here — unlike the API↔worker split below):

```python
class AtCapacity(Exception):
    """No free captcha-browser slot — caller should back off and retry open_for later."""

MAX_CONCURRENT_CAPTCHA_BROWSERS = 4
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CAPTCHA_BROWSERS)
_sessions: dict[str, _Session] = {}   # user_id -> live playwright/browser/context/page

async def open_for(user_id: str, challenge_url: str, cookies: list[dict]) -> tuple[str, bytes | None]:
    """Launch headless Chromium, load `cookies`, navigate to challenge_url.

    Returns ("captcha", png) if hh's widget is present, ("cleared", None) if not
    (wall already lifted), ("token_dead", None) if hh sent the session to a login
    wall instead of a captcha. Raises AtCapacity if the semaphore is exhausted.
    """

async def submit_for(user_id: str, solution: str) -> tuple[str, bytes | None]:
    """Fill SEL_CAPTCHA_INPUT, Enter, re-read the page. Same three-way result as open_for."""

async def cookies_for(user_id: str) -> list[dict]:
    """context.cookies() — call only after a "cleared" result."""

async def close_for(user_id: str) -> None:
    """Close browser/context, stop playwright, release the semaphore slot. No-op if not open."""
```

Both `open_for` and `submit_for` share a `_read_challenge(page)` helper: `/account/login` in
`page.url` → `"token_dead"`; `SEL_CAPTCHA_IMAGE` (reused from `authorize.py`) not found within a
short wait → `"cleared"`; otherwise screenshot the image locator → `"captcha"`. Context is created
via `pw.devices["Galaxy A55"]` (same mobile-emulation profile `authorize.py` uses) so the reused
cookies aren't presented under a different device fingerprint than the one they were issued to.

### 3. `app/worker/runner.py` — `paused_captcha` owns the browser lifecycle, polling the DB

**Correction from the first pass of this section (see above): no in-process queue.** The
challenge URL and the user's typed solution both live on the `captcha_requests` row (`captcha_url`,
new `solution` column below) and the pause loop polls it on `CAPTCHA_POLL_S` (5s, an existing
constant) — the same rhythm every other cross-process signal in this codebase already uses
(`worker_main`'s enabled-flag poll, the `_probe_me` loop this replaces).

Pause-loop shape (`request_id`/`idle_ticks` are loop-local; `_resume_from_captcha` is a nested
closure next to the file's existing `_hb()`, so it shares `handle`/`user_id`/`_hb` by closure):

```python
while handle.state == "paused_captcha":
    if user_id not in web_captcha._sessions:
        try:
            cookies = await form_filler.load_web_cookies(user_id)
        except ValueError:
            await _stop_token_dead("no stored web session")
            return
        pending = await captcha_service.get_pending(user_id)
        request_id = pending[0]["id"] if pending else None
        challenge_url = (pending[0].get("captcha_url") if pending else None) or "https://hh.ru/account/captcha"
        try:
            result, screenshot = await web_captcha.open_for(user_id, challenge_url, cookies)
        except web_captcha.AtCapacity:
            await asyncio.sleep(CAPTCHA_OPEN_RETRY_S)
            continue
        if result == "token_dead":
            await web_captcha.close_for(user_id)
            await _stop_token_dead("captcha page")
            return
        if result == "cleared":
            await _resume_from_captcha()
            continue
        if request_id:
            await captcha_service.attach_screenshot(request_id, screenshot)
        idle_ticks = 0

    await asyncio.sleep(CAPTCHA_POLL_S)
    if handle.state != "paused_captcha":
        break
    solution = await captcha_service.get_solution(request_id) if request_id else None
    if not solution:
        idle_ticks += 1
        if idle_ticks * CAPTCHA_POLL_S > CAPTCHA_BROWSER_IDLE_TIMEOUT_S:
            await web_captcha.close_for(user_id)   # next tick reopens + re-screenshots —
        continue                                    # also catches a wall that cleared on its own

    await captcha_service.clear_solution(request_id)
    result, screenshot = await web_captcha.submit_for(user_id, solution)
    if result == "captcha":                 # wrong answer, hh re-rendered
        if request_id:
            await captcha_service.attach_screenshot(request_id, screenshot)
        idle_ticks = 0
        continue
    if result == "token_dead":
        await web_captcha.close_for(user_id)
        await _stop_token_dead("after captcha submit")
        return
    await _resume_from_captcha()   # "cleared"
```

`_resume_from_captcha()`: `cookies = await web_captcha.cookies_for(user_id)` →
`await web_captcha.close_for(user_id)` → persist via `hh_auth._persist_web_session_only` (already
does encrypt + upsert + drop the cached `requests.Session` + clear the `web_session_expired`
one-shot notice) → `captcha_service.mark_solved(user_id)` → `notify(user_id, "captcha",
{"resolved": True})` → `handle.state = "running"` → `_hb()`.

The whole `paused_captcha` block sits inside `try/finally: if user_id in web_captcha._sessions:
await web_captcha.close_for(user_id)` so a `stop()`-triggered task cancellation (worker turned off
mid-pause) still releases the browser and its semaphore slot.

This retires `_probe_me` entirely — its `WebSessionExpired`/`ValueError` → `token_dead` detection
moves into `open_for`, its `list_resumes()` health check is subsumed by navigating the real
challenge page. Delete it, its now-dead imports (`hh_web`, `WebSessionExpired`, `mark_invalid` —
verify each has no other caller left in the file first), and its 4 dedicated tests.
`WorkerRegistry.resume_captcha` is dead code too — confirmed by the "Correction" section above,
never called outside its own unit test — delete it and that test rather than repurpose it; the API
process has no reachable registry to call into for this flow.

### 4. `app/services/captcha.py` — extend, don't replace

- `create_request(user_id, captcha_url)` — unchanged shape, now actually called with a real URL
  from both trigger points.
- New: `attach_screenshot(request_id, png_bytes) -> None` — uploads to the existing
  `captcha-screenshots` bucket, updates that specific row's `storage_path` (frontend's existing
  Realtime UPDATE subscription on `captcha_requests` picks it up — no frontend schema change).
- New: `get_solution(request_id) -> str | None` / `clear_solution(request_id) -> None` — read and
  null out the new `solution` column.
- `mark_solved`, `get_pending` unchanged.

### 5. Migration — `captcha_requests.solution`

`infra/supabase/migrations/034_captcha_solution.sql`: `ALTER TABLE captcha_requests ADD COLUMN IF
NOT EXISTS solution text;`. No RLS change — only `service_role` (the API's `/solve` handler and the
worker) ever reads or writes it.

### 6. `app/api/captcha.py` — `/solve` writes the DB, no registry involved

```python
class SolveRequest(BaseModel):
    solution: str

@router.post("/{request_id}/solve", response_model=RecheckResponse)
async def solve(request_id: str, body: SolveRequest, user_id=Depends(get_current_user)):
    await captcha_service.submit_solution(user_id, body.solution)
    return RecheckResponse(rechecking=True)
```

`submit_solution(user_id, solution)` = `UPDATE captcha_requests SET solution=... WHERE user_id=...
AND solved=false` (mirrors `mark_solved`'s scoping). `/dismiss` is unchanged — it already just hides
the modal (`mark_solved`) while leaving the runner paused to keep working the row on its own; the
browser-idle-timeout in section 3 is what actually frees resources if the user walks away, not
dismiss.

### 7. `frontend/src/components/captcha-modal.tsx`

Add a text `<input>` + submit button below the image (currently just "я решил, проверить" /
"закрыть", neither takes text). Submit calls
`apiFetch('/api/captcha/${id}/solve', {method: 'POST', body: JSON.stringify({solution})})`. Keep
the existing Realtime subscription — it already re-renders on any `storage_path` UPDATE, so a
"wrong answer" retry (new screenshot, same row) needs no new frontend plumbing beyond clearing the
input on submit. Drop the "открыть на hh" external link and the old copy ("Реши капчу на hh —
worker подхватит сам") since solving now happens in-app.

## Testing

- `tests/test_apply.py`: extend today's `test_apply_one_captcha_when_vacancy_fetch_hits_captcha_wall`
  with a symmetric case for the POST-submit path (mocks `form_filler.submit_response` returning
  `("failed", "captcha_wall: <url>")`).
- `tests/test_web_captcha.py` (new): `open_for`/`submit_for`/`cookies_for`/`close_for` against a
  mocked Playwright (`async_playwright`, browser, context, page) — captcha present → screenshot;
  no widget → cleared; login wall → token_dead; a 5th concurrent `open_for` raises `AtCapacity`.
- `tests/test_runner.py`: extend `paused_captcha` coverage for the new DB-polled shape — a
  `get_solution` returning a value drives `submit_for` and, on `"cleared"`, persists cookies and
  resumes; `"captcha"` (wrong answer) loops without leaving the paused state; no solution for
  longer than `CAPTCHA_BROWSER_IDLE_TIMEOUT_S` closes the browser without ending the pause.

Unit-level only, mocked Playwright/Supabase — no real hh network calls, following existing test
conventions (`_fluent` Supabase mock, `pytest-asyncio`).

## Risk / open items

- The POST-submit captcha fallback path (bare `/account/captcha`, no `state`) is unvalidated —
  no real captured example of a captcha rejection on the POST itself rather than the preceding
  GET. If it turns out hh always captcha-walls the GET first (consistent with what's been observed
  so far), this fallback path may simply never trigger in practice.
- Chromium memory/CPU cost per concurrent captcha-solve session is unmeasured;
  `MAX_CONCURRENT_CAPTCHA_BROWSERS=4` is a starting guess, not a measured ceiling — tune once real
  usage is observed. `# ponytail: fixed global cap, per-plan/tier caps if abuse or resource
  pressure shows up`.
