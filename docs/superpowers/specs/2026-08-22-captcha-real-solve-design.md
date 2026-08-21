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

`app/hh/web.py::CaptchaRequired` already exists (raised by `_get` on `/account/captcha` in
`resp.url`). Add the same check to `form_filler._submit_response`'s pre-submit
`session.get(page_url)` (the GET that fetches xsrf/test-meta before posting): if that response's
`resp.url` contains `/account/captcha`, raise `CaptchaRequired(resp.url)` there too — same
exception class, imported from `app.hh.web`.

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

```python
class CaptchaBrowser:
    async def open(self, challenge_url: str, cookies: list[dict]) -> bytes: ...   # -> screenshot png
    async def submit(self, solution: str) -> tuple[Literal["cleared", "wrong", "no_widget"], bytes | None]: ...
    async def cookies(self) -> list[dict]: ...   # only valid after "cleared"
    async def close(self) -> None: ...

_sessions: dict[str, CaptchaBrowser] = {}          # process-local, keyed by user_id
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CAPTCHA_BROWSERS)  # default 4
```

`open()`: acquire the semaphore (or raise a distinct "at capacity" signal the caller treats as
"stay queued"), launch headless Chromium, `context.add_cookies(cookies)`, navigate to
`challenge_url`, wait for `SEL_CAPTCHA_IMAGE` (reuse `authorize.py`'s selector constants),
screenshot it.

`submit(solution)`: `page.fill(SEL_CAPTCHA_INPUT, solution)` → Enter → wait for navigation/DOM
settle → if `SEL_CAPTCHA_IMAGE` is gone, `"cleared"`; if a (new) captcha image is still present,
screenshot it and return `"wrong"` with the new bytes; if neither hh pattern matches, `"no_widget"`
(treat as cleared).

`close()` releases the semaphore slot and closes the browser/context.

### 3. `app/worker/runner.py` — `paused_captcha` owns the browser lifecycle

Replace `handle.captcha_event: asyncio.Event` with `handle.captcha_solution_queue:
asyncio.Queue[str]`. The challenge URL doesn't need a new field on `RunnerHandle` — it's already
persisted as `captcha_url` on the `captcha_requests` row `apply_one` creates via
`captcha_service.create_request(user_id, challenge_url)`; the pause loop reads it back with
`captcha_service.get_pending(user_id)`.

Pause-loop shape:

```python
while handle.state == "paused_captcha":
    if user_id not in web_captcha._sessions:
        pending = await captcha_service.get_pending(user_id)
        challenge_url = pending[0]["captcha_url"] if pending else "https://hh.ru/account/captcha"
        try:
            screenshot = await web_captcha.open_for(user_id, challenge_url, cookies)
        except AtCapacity:
            await asyncio.sleep(CAPTCHA_QUEUE_RETRY_S)   # e.g. 10s, just re-tries open()
            continue
        await captcha_service.attach_screenshot(user_id, screenshot)  # updates storage_path

    solution = await handle.captcha_solution_queue.get()   # blocks until /solve posts
    result, new_shot = await web_captcha.submit_for(user_id, solution)
    if result in ("cleared", "no_widget"):
        cookies = await web_captcha.cookies_for(user_id)
        await web_captcha.close_for(user_id)
        await persist_refreshed_cookies(user_id, cookies)   # encrypt + save + drop cached session
        await captcha_service.mark_solved(user_id)
        await notify(user_id, "captcha", {"resolved": True})
        handle.state = "running"
    else:  # "wrong"
        await captcha_service.attach_screenshot(user_id, new_shot)   # same row, new storage_path
        # loop back to queue.get()
```

A bounded wait on `queue.get()` (mirroring OAuth's `CAPTCHA_TIMEOUT_SECONDS`) closes the browser
and drops back to "no session open, no pending solution" so an abandoned tab doesn't hold a
Chromium (and a semaphore slot) forever; the pause itself does not end — only the browser does.

### 4. `app/services/captcha.py` — extend, don't replace

- `create_request(user_id, captcha_url)` — unchanged shape, now actually called with a real URL
  from both trigger points.
- New: `attach_screenshot(user_id, png_bytes) -> None` — uploads to the existing
  `captcha-screenshots` bucket, updates the user's open `captcha_requests` row's `storage_path`
  (same row, so the frontend's existing Realtime UPDATE subscription picks it up — no schema
  change).
- `mark_solved` unchanged.

### 5. `app/api/captcha.py` — `/solve` gets a body

```python
class SolveRequest(BaseModel):
    solution: str

@router.post("/{request_id}/solve", response_model=RecheckResponse)
async def solve(request_id: str, body: SolveRequest, user_id=Depends(get_current_user)):
    get_registry().submit_captcha_solution(user_id, body.solution)  # puts onto the queue
    return RecheckResponse(rechecking=True)
```

`/dismiss` additionally calls a new `get_registry().close_captcha_browser(user_id)` (frees the
browser/semaphore slot; runner stays `paused_captcha` with no auto-recovery — the user must come
back and solve it, or stop the worker).

### 6. `frontend/src/components/captcha-modal.tsx`

Add a text `<input>` + submit button below the image (currently just "я решил, проверить" /
"закрыть", neither takes text). Submit calls
`apiFetch('/api/captcha/${id}/solve', {method: 'POST', body: JSON.stringify({solution})})`. Keep
the existing Realtime subscription — it already re-renders on any `storage_path` UPDATE, so a
"wrong answer" retry (new screenshot, same row) needs no new frontend plumbing beyond clearing the
input on submit. Drop the "открыть на hh" external link and the old copy ("Реши капчу на hh —
worker подхватит сам") since solving now happens in-app.

## Testing

- `tests/test_apply.py`: extend today's `test_apply_one_captcha_when_vacancy_fetch_hits_captcha_wall`
  with a symmetric `test_apply_one_captcha_when_submit_hits_captcha_wall` (mocks
  `form_filler.submit_response` raising `web.CaptchaRequired`).
- `tests/test_web_captcha.py` (new): `CaptchaBrowser` against a mocked Playwright
  page/context (open → screenshot; submit wrong → new screenshot; submit right → cleared;
  semaphore denies a 5th concurrent `open`).
- `tests/test_runner.py`: extend the `paused_captcha` coverage — queue delivers a solution →
  `"cleared"` resumes and persists cookies; `"wrong"` loops without leaving the paused state;
  queue timeout closes the browser without ending the pause.

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
