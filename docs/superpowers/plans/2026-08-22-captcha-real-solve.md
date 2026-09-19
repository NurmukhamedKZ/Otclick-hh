# Real Captcha Solving Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user actually clear an hh.ru captcha that's blocking the worker's web session — see the real captcha image (rendered from the worker's own cookie session via a headless browser), type the answer, submit, and have auto-apply resume — instead of today's non-functional "go solve it on hh.ru yourself" modal.

**Architecture:** Both places `apply.py` detects hh's `/account/captcha` redirect (GET vacancy fetch, POST negotiation submit) now carry the real challenge URL into a `captcha_requests` row. The worker's `paused_captcha` loop (already exists) owns a new `app/hh/web_captcha.py` service that loads the stored cookies into a headless Playwright browser, screenshots hh's captcha widget, and polls a new `captcha_requests.solution` DB column for the answer the user types into the dashboard modal — DB-polled rather than an in-process channel, because `api` and `worker` are separate containers with no shared memory. On a correct answer, refreshed cookies are persisted and the runner resumes.

**Tech Stack:** FastAPI backend, Playwright (already a dependency, already used for the identical captcha widget in `app/hh/authorize.py`), Supabase/Postgres, Next.js frontend, pytest/pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-08-22-captcha-real-solve-design.md`

## Global Constraints

- `api` and `worker` are separate containers (`docker-compose.yml`) with no shared memory — every cross-process signal goes through the database, polled on a timer (`CAPTCHA_POLL_S`).
- Reuse `app/hh/authorize.py`'s selectors (`SEL_CAPTCHA_IMAGE`, `SEL_CAPTCHA_INPUT`) and its `pw.devices["Galaxy A55"]` context profile — the stored cookies were captured under that same mobile-emulation fingerprint.
- No AI auto-solving of the captcha image — a human types the answer.
- `MAX_CONCURRENT_CAPTCHA_BROWSERS = 4` global semaphore, matching `hh_auth.MAX_CONCURRENT_JOBS`'s existing precedent — never spin unbounded Chromium instances.
- Follow existing test conventions: unit-level only, `_fluent`/`_insert_mock`-style mocked Supabase chains, mocked Playwright, `pytest-asyncio`, env vars set via `os.environ.setdefault` at the top of each test file (already present in every file this plan touches).
- Every changed line must trace to this feature — do not refactor unrelated code you pass over.

---

### Task 1: Move `CaptchaRequired` into `form_filler.py` with a real `url` attribute

**Files:**
- Modify: `backend/app/services/form_filler.py:40-41` (insert after `WebSessionExpired`)
- Modify: `backend/app/hh/web.py:23-28,36-41,62-63` (import instead of define; pass the real URL)
- Modify: `backend/app/services/apply.py:237-241` (use `ex.url` instead of a static string)
- Test: `backend/tests/test_apply.py` (update the existing captcha test's assertion)

**Interfaces:**
- Produces: `form_filler.CaptchaRequired(url: str)` — `Exception` subclass with a `.url` attribute holding the hh challenge page URL (e.g. `https://hh.ru/account/captcha?backurl=...&state=...`). Re-exported as `web.CaptchaRequired` (same class object, imported not redefined) so existing `except web.CaptchaRequired` call sites keep working unchanged.

- [ ] **Step 1: Add the failing/updated test first**

In `backend/tests/test_apply.py`, find `test_apply_one_captcha_when_vacancy_fetch_hits_captcha_wall` (added in the prior session) and update it to assert the real URL is threaded through to `create_request`:

```python
async def test_apply_one_captcha_when_vacancy_fetch_hits_captcha_wall():
    """hh redirecting the web session to /account/captcha must pause the
    worker via the existing captcha flow, not fall through as a generic
    "failed" (which silently re-queues the same vacancy forever), and must
    carry the real challenge URL through to the captcha_requests row."""
    from app.hh import web as web_mod
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1"})
    captcha_calls = []

    async def _captcha(user_id, vacancy_id):
        raise web_mod.CaptchaRequired("https://hh.ru/account/captcha?state=abc123")

    async def fake_create_request(user_id, captcha_url):
        captcha_calls.append((user_id, captcha_url))

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_captcha),
        patch.object(apply_mod.captcha_service, "create_request", side_effect=fake_create_request),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "captcha"
    assert captcha_calls == [("u1", "https://hh.ru/account/captcha?state=abc123")]
```

This replaces the existing version of the test (which asserted `captcha_calls == [("u1", None)]`).

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_apply.py::test_apply_one_captcha_when_vacancy_fetch_hits_captcha_wall -v`
Expected: FAIL — `captcha_calls == [("u1", None)]` (the current code still passes `None`, and `CaptchaRequired("https://...")` still works as a plain message-only exception since it has no `.url` yet, so this specific assertion fails on the tuple mismatch, not a crash).

- [ ] **Step 3: Move `CaptchaRequired` into `form_filler.py`**

In `backend/app/services/form_filler.py`, right after the existing `WebSessionExpired` class (currently lines 40-41):

```python
class WebSessionExpired(Exception):
    """hh no longer accepts the stored web cookies — the user must reconnect."""


class CaptchaRequired(Exception):
    """hh redirected the web session to a captcha wall (/account/captcha)."""

    def __init__(self, url: str):
        super().__init__(url)
        self.url = url
```

- [ ] **Step 4: Update `web.py` to import it instead of defining its own, and pass the real URL**

In `backend/app/hh/web.py`, change the import block (currently lines 24-28):

```python
from app.services.form_filler import (
    CaptchaRequired,
    WebSessionExpired,
    load_web_session,
    session_looks_dead,
)
```

Remove the locally-defined class (currently lines 40-41):

```python
class VacancyGone(Exception):
    """hh no longer serves this vacancy page (404/410) — archived or deleted."""


class CaptchaRequired(Exception):
    """hh redirected the web session to a captcha wall (/account/captcha)."""
```

becomes:

```python
class VacancyGone(Exception):
    """hh no longer serves this vacancy page (404/410) — archived or deleted."""
```

And fix the raise (currently line 63) from:

```python
    if "/account/captcha" in (resp.url or ""):
        raise CaptchaRequired("hh redirected the web session to a captcha wall")
```

to:

```python
    if "/account/captcha" in (resp.url or ""):
        raise CaptchaRequired(resp.url)
```

- [ ] **Step 5: Update `apply.py` to use `ex.url`**

In `backend/app/services/apply.py`, the GET-vacancy except block currently reads:

```python
    except web.CaptchaRequired:
        logger.warning("apply: user=%s vacancy=%s captcha on vacancy fetch", user_id, vacancy_id)
        await loop.run_in_executor(
            None,
            lambda: _record_application(
                user_id=user_id,
                resume_uuid=resume_uuid,
                vacancy_id=vacancy_id,
                status="captcha",
                cover_letter=None,
                error="captcha on vacancy fetch",
            ),
        )
        try:
            await captcha_service.create_request(user_id, None)
        except Exception:
            logger.exception("apply: failed to create captcha_request")
        return "captcha"
```

Change to:

```python
    except web.CaptchaRequired as ex:
        logger.warning("apply: user=%s vacancy=%s captcha on vacancy fetch", user_id, vacancy_id)
        await loop.run_in_executor(
            None,
            lambda: _record_application(
                user_id=user_id,
                resume_uuid=resume_uuid,
                vacancy_id=vacancy_id,
                status="captcha",
                cover_letter=None,
                error="captcha on vacancy fetch",
            ),
        )
        try:
            await captcha_service.create_request(user_id, ex.url)
        except Exception:
            logger.exception("apply: failed to create captcha_request")
        return "captcha"
```

- [ ] **Step 6: Run the test to confirm it passes**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_apply.py::test_apply_one_captcha_when_vacancy_fetch_hits_captcha_wall -v`
Expected: PASS

- [ ] **Step 7: Run the full backend test suite to catch any other breakage**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/ -q --ignore=tests/integration --ignore=tests/e2e`
Expected: all pass (this only touches exception plumbing shared by `web.py`/`form_filler.py`/`apply.py`, no other call sites reference the old `CaptchaRequired` shape).

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/form_filler.py backend/app/hh/web.py backend/app/services/apply.py backend/tests/test_apply.py
git commit -m "fix: carry the real hh captcha challenge URL through CaptchaRequired

Moves CaptchaRequired into form_filler.py (web.py already imports FROM
form_filler.py, so the reverse import was circular) and gives it a
real .url attribute instead of a static placeholder message, so the
captcha_requests row created downstream has an actual challenge page
to open."
```

---

### Task 2: Detect captcha on the POST-submit path; retire the fragile substring probe

**Files:**
- Modify: `backend/app/services/form_filler.py` (the `_submit_response`/`submit_response` pair, currently around lines 430-454 and 547-579)
- Modify: `backend/app/services/apply.py:452-475` (replace `"captcha" in err_text` with an exact-tag check)
- Test: `backend/tests/test_apply.py` (update `test_apply_one_captcha_does_not_fall_through_to_failed`)

**Interfaces:**
- Consumes: `form_filler.CaptchaRequired` from Task 1.
- Produces: `form_filler.submit_response(...)` now returns `("failed", f"captcha_wall: {url}")` when hh captcha-walls the pre-submit GET. `apply.py` recognizes this exact tag (`error.startswith("captcha_wall: ")`) instead of scanning for the substring `"captcha"` anywhere in the rejection body.

- [ ] **Step 1: Update the existing test to the new detection contract first**

In `backend/tests/test_apply.py`, `test_apply_one_captcha_does_not_fall_through_to_failed` currently mocks `submit_response` returning `("failed", "hh_rejected: 200 {\"error\":\"captcha required\"}")`. Change the mock to the real tag `_submit_response` will now produce:

```python
async def test_apply_one_captcha_does_not_fall_through_to_failed():
    """A captcha wall classified as "failed" leaves the runner hammering hh
    while the UI reports healthy — the fastest route to a flagged account."""
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1", "title": "T"})

    async def _vacancy(user_id, vacancy_id):
        return {
            "id": "v1",
            "employer": {"id": "42", "name": "Acme"},
            "has_test": False,
            "response_letter_required": False,
        }

    async def _submitted(user_id, resume_id, vacancy_id, letter="", answers=None):
        return "failed", "captcha_wall: https://hh.ru/account/captcha?state=xyz"

    created = []

    async def _create(user_id, captcha_url):
        created.append((user_id, captcha_url))
        return {}

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_vacancy),
        patch.object(apply_mod.form_filler, "submit_response", new=_submitted),
        patch.object(apply_mod.captcha_service, "create_request", new=_create),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "captcha"
    assert created == [("u1", "https://hh.ru/account/captcha?state=xyz")]
```

(Previously the test only asserted `created == ["u1"]` against a list of user ids; `create_request` is now called with the real URL, so the fixture and assertion both change shape.)

- [ ] **Step 2: Also add a new test for the raw `_submit_response`/`submit_response` detection**

Append to `backend/tests/test_apply.py` (or, if you prefer keeping form_filler tests together, to `backend/tests/test_form_filler.py` if one exists — check with `ls backend/tests/test_form_filler.py`; if absent, add it to `test_apply.py` next to the test from Step 1):

```python
async def test_submit_response_returns_captcha_wall_tag_on_captcha_redirect():
    """form_filler.submit_response must surface hh's real captcha URL as an
    exact "captcha_wall: <url>" tag, not bury it in a generic submit_error —
    apply.py matches this exact prefix, not a loose substring."""
    from unittest.mock import MagicMock

    from app.services import form_filler as ff

    session = MagicMock()
    get_resp = MagicMock()
    get_resp.url = "https://hh.ru/account/captcha?backurl=https%3A%2F%2Fhh.ru%2Fvacancy%2Fv1&state=abc"
    session.get.return_value = get_resp

    async def _fake_session(user_id):
        return session

    async def _fake_resume_id(user_id, resume_id):
        return "hh-r1"

    with (
        patch.object(ff, "load_web_session", new=_fake_session),
        patch.object(ff, "_get_hh_resume_id", new=_fake_resume_id),
    ):
        status, error = await ff.submit_response("u1", "r-uuid", "v1", letter="hi", answers=None)

    assert status == "failed"
    assert error == "captcha_wall: https://hh.ru/account/captcha?backurl=https%3A%2F%2Fhh.ru%2Fvacancy%2Fv1&state=abc"
```

- [ ] **Step 3: Run both to confirm they fail**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_apply.py::test_apply_one_captcha_does_not_fall_through_to_failed tests/test_apply.py::test_submit_response_returns_captcha_wall_tag_on_captcha_redirect -v`
Expected: both FAIL (the first on the changed assertion shape, the second because `_submit_response` doesn't raise `CaptchaRequired` yet — it currently just returns `_post_response`'s rejection normally, so `status` won't be `"failed"` with that exact error text, or the mock's incomplete `_post_response` chain will error — either way, not the expected tuple).

- [ ] **Step 4: Add the captcha check to `_submit_response`**

In `backend/app/services/form_filler.py`, `_submit_response` currently reads:

```python
def _submit_response(
    session: requests.Session,
    vacancy_id: str,
    hh_resume_id: str,
    letter: str,
    answers: list[dict] | None,
) -> requests.Response:
    """Fetch the response page (fresh xsrf; test meta only if answers given),
    build the payload and POST."""
    # xsrf comes from the page the browser would be on when it submits: the
    # vacancy page for a plain response, the popup only when a test has to be
    # parsed out of it.
    page_url = _response_url(vacancy_id) if answers else f"https://hh.ru/vacancy/{vacancy_id}"
    r = session.get(page_url, timeout=15)
    if session_looks_dead(r):
        raise WebSessionExpired(f"hh rejected the web session ({r.status_code})")
    r.raise_for_status()
```

Change to:

```python
def _submit_response(
    session: requests.Session,
    vacancy_id: str,
    hh_resume_id: str,
    letter: str,
    answers: list[dict] | None,
) -> requests.Response:
    """Fetch the response page (fresh xsrf; test meta only if answers given),
    build the payload and POST."""
    # xsrf comes from the page the browser would be on when it submits: the
    # vacancy page for a plain response, the popup only when a test has to be
    # parsed out of it.
    page_url = _response_url(vacancy_id) if answers else f"https://hh.ru/vacancy/{vacancy_id}"
    r = session.get(page_url, timeout=15)
    if "/account/captcha" in (r.url or ""):
        raise CaptchaRequired(r.url)
    if session_looks_dead(r):
        raise WebSessionExpired(f"hh rejected the web session ({r.status_code})")
    r.raise_for_status()
```

- [ ] **Step 5: Catch it in `submit_response` (the async wrapper) before the generic `Exception` handler**

Still in `backend/app/services/form_filler.py`, `submit_response` currently reads:

```python
    try:
        resp = await loop.run_in_executor(
            None, _submit_response, session, vacancy_id, hh_resume_id, letter, answers
        )
    except WebSessionExpired as ex:
        await report_dead_session(user_id, ex)
        return "failed", f"web_session_expired: {ex}"
    except Exception as ex:
        logger.exception("fill: submit failed vacancy=%s", vacancy_id)
        return "failed", f"submit_error: {ex}"
```

Change to:

```python
    try:
        resp = await loop.run_in_executor(
            None, _submit_response, session, vacancy_id, hh_resume_id, letter, answers
        )
    except CaptchaRequired as ex:
        return "failed", f"captcha_wall: {ex.url}"
    except WebSessionExpired as ex:
        await report_dead_session(user_id, ex)
        return "failed", f"web_session_expired: {ex}"
    except Exception as ex:
        logger.exception("fill: submit failed vacancy=%s", vacancy_id)
        return "failed", f"submit_error: {ex}"
```

(`CaptchaRequired` is defined in this same module from Task 1 — no new import needed.)

- [ ] **Step 6: Replace the fragile substring check in `apply.py`**

In `backend/app/services/apply.py`, the block currently reads (starting at the `err_text = ` line):

```python
    err_text = (error or "").lower()
    # Captcha must NOT fall through to "failed": the runner would keep applying
    # into a captcha wall while looking healthy, which is the fastest way to get
    # the account flagged. ponytail: substring probe — the web captcha body was
    # never captured in recon, tighten it once a real one is seen.
    if "captcha" in err_text:
        logger.warning("apply: user=%s vacancy=%s captcha on submit", user_id, vacancy_id)
        await loop.run_in_executor(
            None,
            lambda: _record_application(
                user_id=user_id,
                resume_uuid=resume_uuid,
                vacancy_id=vacancy_id,
                status="captcha",
                cover_letter=cover_letter or None,
                error=error,
                employer_id=employer_id,
            ),
        )
        try:
            await captcha_service.create_request(user_id, None)
        except Exception:
            logger.exception("apply: failed to create captcha_request")
        return "captcha"
```

Change to:

```python
    err_text = (error or "").lower()
    # Captcha must NOT fall through to "failed": the runner would keep applying
    # into a captcha wall while looking healthy, which is the fastest way to get
    # the account flagged. The precise case — hh's own /account/captcha redirect
    # on the pre-submit GET — is tagged exactly as "captcha_wall: <url>" by
    # form_filler.CaptchaRequired. The substring fallback stays for a POST
    # rejected directly (no preceding GET redirect) — never captured in recon,
    # so there's no real URL to open for it; web_captcha falls back to a bare
    # https://hh.ru/account/captcha in that case (see app/worker/runner.py).
    if error and error.startswith("captcha_wall: "):
        challenge_url = error[len("captcha_wall: "):]
        logger.warning("apply: user=%s vacancy=%s captcha on submit", user_id, vacancy_id)
        await loop.run_in_executor(
            None,
            lambda: _record_application(
                user_id=user_id,
                resume_uuid=resume_uuid,
                vacancy_id=vacancy_id,
                status="captcha",
                cover_letter=cover_letter or None,
                error=error,
                employer_id=employer_id,
            ),
        )
        try:
            await captcha_service.create_request(user_id, challenge_url)
        except Exception:
            logger.exception("apply: failed to create captcha_request")
        return "captcha"
    if "captcha" in err_text:
        logger.warning(
            "apply: user=%s vacancy=%s captcha on submit (no challenge URL — "
            "POST rejected directly, not the pre-submit GET)",
            user_id, vacancy_id,
        )
        await loop.run_in_executor(
            None,
            lambda: _record_application(
                user_id=user_id,
                resume_uuid=resume_uuid,
                vacancy_id=vacancy_id,
                status="captcha",
                cover_letter=cover_letter or None,
                error=error,
                employer_id=employer_id,
            ),
        )
        try:
            await captcha_service.create_request(user_id, None)
        except Exception:
            logger.exception("apply: failed to create captcha_request")
        return "captcha"
```

(`err_text` stays — the very next `if any(m in err_text for m in _ALREADY_APPLIED_MARKERS):` block still needs it.)

Add a test for the fallback branch too, appended to `backend/tests/test_apply.py`:

```python
async def test_apply_one_captcha_fallback_when_post_rejects_without_challenge_url():
    """No preceding-GET redirect captured (hh rejected the POST itself) —
    still must not fall through to "failed", even with no known challenge URL."""
    from app.services import apply as apply_mod

    sb, _, _ = _supabase_mock({"id": "r-uuid", "hh_resume_id": "hh-r1", "title": "T"})

    async def _vacancy(user_id, vacancy_id):
        return {
            "id": "v1",
            "employer": {"id": "42", "name": "Acme"},
            "has_test": False,
            "response_letter_required": False,
        }

    async def _submitted(user_id, resume_id, vacancy_id, letter="", answers=None):
        return "failed", "hh_rejected: 200 {\"error\":\"captcha required\"}"

    created = []

    async def _create(user_id, captcha_url):
        created.append((user_id, captcha_url))
        return {}

    with (
        patch.object(apply_mod, "service_client", sb),
        patch.object(apply_mod.web, "get_vacancy", new=_vacancy),
        patch.object(apply_mod.form_filler, "submit_response", new=_submitted),
        patch.object(apply_mod.captcha_service, "create_request", new=_create),
    ):
        result = await apply_mod.apply_one("u1", "r-uuid", "v1", _fake_agent())
    assert result == "captcha"
    assert created == [("u1", None)]
```

- [ ] **Step 7: Run the tests to confirm they pass**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_apply.py::test_apply_one_captcha_does_not_fall_through_to_failed tests/test_apply.py::test_apply_one_captcha_fallback_when_post_rejects_without_challenge_url tests/test_apply.py::test_submit_response_returns_captcha_wall_tag_on_captcha_redirect -v`
Expected: PASS (3 tests)

- [ ] **Step 8: Run the full backend suite**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/ -q --ignore=tests/integration --ignore=tests/e2e`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/form_filler.py backend/app/services/apply.py backend/tests/test_apply.py
git commit -m "fix: detect the POST-submit hh captcha wall by URL, not body substring

form_filler._submit_response's pre-submit GET now raises CaptchaRequired
on the same /account/captcha redirect the vacancy-fetch path already
catches, tagged through as \"captcha_wall: <url>\" so apply.py can match
an exact prefix instead of guessing from a truncated rejection body."
```

---

### Task 3: `captcha_requests.solution` migration

**Files:**
- Create: `infra/supabase/migrations/034_captcha_solution.sql`

**Interfaces:**
- Produces: `captcha_requests.solution` (nullable `text` column) — the user's typed captcha answer, written by the API's `/solve` endpoint (Task 6), read and cleared by the worker's pause loop (Task 7).

- [ ] **Step 1: Write the migration**

```sql
-- ============================================================
-- 034_captcha_solution.sql — real captcha solving, worker's web session.
-- POST /api/captcha/{id}/solve now writes the user's typed answer here
-- instead of just marking the row solved; the worker (a separate process —
-- no in-memory channel reaches it from the API) polls for it and types it
-- into the live Playwright session holding the account's cookies.
-- ============================================================

ALTER TABLE captcha_requests ADD COLUMN IF NOT EXISTS solution text;
```

- [ ] **Step 2: Apply it against the local stack**

Run: `cd /Users/nurma/vscode_projects/AIautoclicker && docker compose up migrate`
Expected: log output shows `034_captcha_solution.sql` applied (or already-applied on a re-run — the migrate script is idempotent, tracked in `public.schema_migrations`).

- [ ] **Step 3: Verify the column exists**

Run: `docker exec -it aiautoclicker-db psql -U postgres -d postgres -c "\d captcha_requests"`
Expected: `solution` listed as a nullable `text` column.

- [ ] **Step 4: Commit**

```bash
git add infra/supabase/migrations/034_captcha_solution.sql
git commit -m "feat: add captcha_requests.solution column for real captcha solving"
```

---

### Task 4: Extend `app/services/captcha.py` — screenshot attach + solution read/write

**Files:**
- Modify: `backend/app/services/captcha.py`
- Test: `backend/tests/test_captcha.py`

**Interfaces:**
- Consumes: `service_client` (already imported in this module), the `solution` column from Task 3.
- Produces:
  - `attach_screenshot(request_id: str, png: bytes) -> None`
  - `get_solution(request_id: str) -> str | None`
  - `clear_solution(request_id: str) -> None`
  - `submit_solution(user_id: str, solution: str) -> None`
  (all `async`, matching the module's existing `run_in_executor` pattern)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_captcha.py`:

```python
async def test_attach_screenshot_uploads_and_updates_storage_path():
    from app.services import captcha as captcha_mod

    table_chain = _insert_mock({"id": "c1"})
    storage_bucket = MagicMock()
    sb = MagicMock()
    sb.table.return_value = table_chain
    sb.storage.from_.return_value = storage_bucket

    with patch.object(captcha_mod, "service_client", sb):
        await captcha_mod.attach_screenshot("c1", b"PNGDATA")

    storage_bucket.upload.assert_called_once()
    update_arg = table_chain.update.call_args[0][0]
    assert update_arg["storage_path"]
    eq_calls = [c.args for c in table_chain.eq.call_args_list]
    assert ("id", "c1") in eq_calls


async def test_get_solution_reads_the_column():
    from app.services import captcha as captcha_mod

    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.maybe_single.return_value = chain
    chain.execute.return_value = SimpleNamespace(data={"solution": "AB12"})
    sb = MagicMock()
    sb.table.return_value = chain

    with patch.object(captcha_mod, "service_client", sb):
        result = await captcha_mod.get_solution("c1")

    assert result == "AB12"
    eq_calls = [c.args for c in chain.eq.call_args_list]
    assert ("id", "c1") in eq_calls


async def test_get_solution_returns_none_when_column_empty():
    from app.services import captcha as captcha_mod

    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.maybe_single.return_value = chain
    chain.execute.return_value = SimpleNamespace(data={"solution": None})
    sb = MagicMock()
    sb.table.return_value = chain

    with patch.object(captcha_mod, "service_client", sb):
        assert await captcha_mod.get_solution("c1") is None


async def test_clear_solution_nulls_the_column():
    from app.services import captcha as captcha_mod

    chain = _insert_mock(None)
    sb = MagicMock()
    sb.table.return_value = chain

    with patch.object(captcha_mod, "service_client", sb):
        await captcha_mod.clear_solution("c1")

    update_arg = chain.update.call_args[0][0]
    assert update_arg == {"solution": None}
    eq_calls = [c.args for c in chain.eq.call_args_list]
    assert ("id", "c1") in eq_calls


async def test_submit_solution_scoped_to_user_and_unsolved():
    from app.services import captcha as captcha_mod

    chain = _insert_mock(None)
    sb = MagicMock()
    sb.table.return_value = chain

    with patch.object(captcha_mod, "service_client", sb):
        await captcha_mod.submit_solution("u1", "AB12")

    update_arg = chain.update.call_args[0][0]
    assert update_arg == {"solution": "AB12"}
    eq_calls = [c.args for c in chain.eq.call_args_list]
    assert ("user_id", "u1") in eq_calls
    assert ("solved", False) in eq_calls
```

- [ ] **Step 2: Run to confirm they fail**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_captcha.py -v`
Expected: the 5 new tests FAIL with `AttributeError: module 'app.services.captcha' has no attribute 'attach_screenshot'` (etc.); the 3 pre-existing tests still pass.

- [ ] **Step 3: Implement the four functions**

Append to `backend/app/services/captcha.py` (after the existing `get_pending`):

```python
def _attach_screenshot_sync(request_id: str, png: bytes) -> None:
    path = f"{uuid.uuid4()}.png"
    try:
        service_client.storage.from_(SCREENSHOT_BUCKET).upload(
            path, png, {"content-type": "image/png", "upsert": "true"}
        )
    except Exception:
        logger.warning("captcha: screenshot upload failed for request %s", request_id, exc_info=True)
        return
    (
        service_client.table("captcha_requests")
        .update({"storage_path": path})
        .eq("id", request_id)
        .execute()
    )


async def attach_screenshot(request_id: str, png: bytes) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _attach_screenshot_sync, request_id, png)


def _get_solution_sync(request_id: str) -> str | None:
    res = (
        service_client.table("captcha_requests")
        .select("solution")
        .eq("id", request_id)
        .maybe_single()
        .execute()
    )
    data = res.data if res else None
    return (data or {}).get("solution")


async def get_solution(request_id: str) -> str | None:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _get_solution_sync, request_id)


def _clear_solution_sync(request_id: str) -> None:
    (
        service_client.table("captcha_requests")
        .update({"solution": None})
        .eq("id", request_id)
        .execute()
    )


async def clear_solution(request_id: str) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _clear_solution_sync, request_id)


def _submit_solution_sync(user_id: str, solution: str) -> None:
    (
        service_client.table("captcha_requests")
        .update({"solution": solution})
        .eq("user_id", user_id)
        .eq("solved", False)
        .execute()
    )


async def submit_solution(user_id: str, solution: str) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _submit_solution_sync, user_id, solution)
```

Add `import uuid` to the top of `backend/app/services/captcha.py` if not already present (check the existing import block — `_create_request_sync` already builds a path with `uuid.uuid4()`, so `import uuid` should already be there; if so, skip this).

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_captcha.py -v`
Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/captcha.py backend/tests/test_captcha.py
git commit -m "feat: add screenshot-attach and solution read/write to captcha service"
```

---

### Task 5: `form_filler.load_web_cookies` — raw decrypted cookies for Playwright

**Files:**
- Modify: `backend/app/services/form_filler.py`
- Test: `backend/tests/test_form_filler.py` if it exists (check with `ls backend/tests/test_form_filler.py`); otherwise add to `backend/tests/test_apply.py`

**Interfaces:**
- Produces: `async def load_web_cookies(user_id: str) -> list[dict]` — the decrypted cookie list exactly as stored (Playwright's own `context.cookies()` shape: `name`/`value`/`domain`/`path`/...), for callers that need raw cookies rather than a `requests.Session`. Raises `ValueError` if no session is stored (same contract as `load_web_session`).

- [ ] **Step 1: Write the failing test**

```python
async def test_load_web_cookies_returns_decrypted_list():
    from app.services import form_filler as ff

    async def _fake_enc(user_id):
        return "encrypted-blob"

    with (
        patch.object(ff, "_load_cookies_encrypted", new=_fake_enc),
        patch.object(ff, "decrypt_token", return_value='[{"name": "a", "value": "b", "domain": "hh.ru", "path": "/"}]'),
    ):
        cookies = await ff.load_web_cookies("u1")

    assert cookies == [{"name": "a", "value": "b", "domain": "hh.ru", "path": "/"}]


async def test_load_web_cookies_raises_when_nothing_stored():
    from app.services import form_filler as ff

    async def _none(user_id):
        return None

    with patch.object(ff, "_load_cookies_encrypted", new=_none):
        with pytest.raises(ValueError):
            await ff.load_web_cookies("u1")
```

Note: `_load_cookies_encrypted` is a plain sync function called via `run_in_executor` elsewhere in the module — `patch.object(ff, "_load_cookies_encrypted", new=_fake_enc)` replaces it with an async stand-in here only to keep the test simple; since `load_web_cookies` will call it the same way `load_web_session` does (via `loop.run_in_executor(None, _load_cookies_encrypted, user_id)`), and `run_in_executor` requires a plain callable (not a coroutine function) in production — for the test, patch it as a **sync** function instead:

```python
async def test_load_web_cookies_returns_decrypted_list():
    from app.services import form_filler as ff

    def _fake_enc(user_id):
        return "encrypted-blob"

    with (
        patch.object(ff, "_load_cookies_encrypted", side_effect=_fake_enc),
        patch.object(ff, "decrypt_token", return_value='[{"name": "a", "value": "b", "domain": "hh.ru", "path": "/"}]'),
    ):
        cookies = await ff.load_web_cookies("u1")

    assert cookies == [{"name": "a", "value": "b", "domain": "hh.ru", "path": "/"}]


async def test_load_web_cookies_raises_when_nothing_stored():
    import pytest

    from app.services import form_filler as ff

    with patch.object(ff, "_load_cookies_encrypted", return_value=None):
        with pytest.raises(ValueError):
            await ff.load_web_cookies("u1")
```

Use this second version (plain `MagicMock`-style `return_value`/`side_effect`, no async stand-in) — it matches how `_load_cookies_encrypted` is actually invoked via `run_in_executor`.

- [ ] **Step 2: Run to confirm it fails**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_apply.py::test_load_web_cookies_returns_decrypted_list tests/test_apply.py::test_load_web_cookies_raises_when_nothing_stored -v`
(adjust the file path if you placed these in `test_form_filler.py` instead)
Expected: FAIL — `AttributeError: module 'app.services.form_filler' has no attribute 'load_web_cookies'`.

- [ ] **Step 3: Implement it**

In `backend/app/services/form_filler.py`, right after `load_web_session` (which currently ends around line 111 with `return session`):

```python
async def load_web_cookies(user_id: str) -> list[dict]:
    """Raw decrypted cookie list — for callers that need cookies outside a
    requests.Session (Playwright's context.add_cookies wants this exact shape,
    which is also exactly how they're stored: captured via context.cookies()
    during OAuth login, JSON-serialized as-is). Raises ValueError if no
    session is stored, same contract as load_web_session."""
    loop = asyncio.get_running_loop()
    enc = await loop.run_in_executor(None, _load_cookies_encrypted, user_id)
    if not enc:
        raise ValueError(f"no stored web session for user {user_id} — reconnect required")
    return json.loads(decrypt_token(enc))
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_apply.py::test_load_web_cookies_returns_decrypted_list tests/test_apply.py::test_load_web_cookies_raises_when_nothing_stored -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/form_filler.py backend/tests/test_apply.py
git commit -m "feat: add form_filler.load_web_cookies for Playwright-based captcha solving"
```

---

### Task 6: `app/hh/web_captcha.py` — the Playwright solving service

**Files:**
- Create: `backend/app/hh/web_captcha.py`
- Test: `backend/tests/test_web_captcha.py`

**Interfaces:**
- Consumes: `app.hh.authorize.SEL_CAPTCHA_IMAGE`, `SEL_CAPTCHA_INPUT` (existing constants).
- Produces:
  - `class AtCapacity(Exception)`
  - `MAX_CONCURRENT_CAPTCHA_BROWSERS: int = 4`
  - `async def open_for(user_id: str, challenge_url: str, cookies: list[dict]) -> tuple[str, bytes | None]`
  - `async def submit_for(user_id: str, solution: str) -> tuple[str, bytes | None]`
  - `async def cookies_for(user_id: str) -> list[dict]`
  - `async def close_for(user_id: str) -> None`
  - `_sessions: dict[str, _Session]` (module-level, process-local — tests and `conftest.py` reset this between runs)

  Result strings from `open_for`/`submit_for`: `"captcha"` (widget present, `bytes` screenshot), `"cleared"` (no widget — wall already lifted, `None`), `"token_dead"` (redirected to a login wall instead, `None`).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_web_captcha.py`:

```python
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")

import pytest


def _fake_playwright(page_url="https://hh.ru/account/captcha?state=abc", has_widget=True):
    """A mock async_playwright() context manager whose chromium.launch()
    yields a browser/context/page chain matching Playwright's real API shape
    closely enough for web_captcha to drive it."""
    page = MagicMock()
    page.url = page_url
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock(
        side_effect=None if has_widget else TimeoutError("not found")
    )
    locator = MagicMock()
    locator.screenshot = AsyncMock(return_value=b"PNGDATA")
    page.locator.return_value = locator
    page.fill = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.wait_for_load_state = AsyncMock()

    context = MagicMock()
    context.add_cookies = AsyncMock()
    context.new_page = AsyncMock(return_value=page)
    context.cookies = AsyncMock(return_value=[{"name": "a", "value": "b"}])

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    pw_instance = MagicMock()
    pw_instance.chromium.launch = AsyncMock(return_value=browser)
    pw_instance.devices = {"Galaxy A55": {}}
    pw_instance.stop = AsyncMock()

    pw_factory = MagicMock()
    pw_factory.start = AsyncMock(return_value=pw_instance)
    return pw_factory, page, context, browser


async def test_open_for_returns_captcha_with_screenshot():
    from app.hh import web_captcha

    web_captcha._sessions.clear()
    pw_factory, page, context, browser = _fake_playwright(has_widget=True)

    with patch.object(web_captcha, "async_playwright", return_value=pw_factory):
        result, screenshot = await web_captcha.open_for("u1", "https://hh.ru/account/captcha", [])

    assert result == "captcha"
    assert screenshot == b"PNGDATA"
    context.add_cookies.assert_called_once_with([])
    await web_captcha.close_for("u1")


async def test_open_for_returns_cleared_when_no_widget():
    from app.hh import web_captcha

    web_captcha._sessions.clear()
    pw_factory, page, context, browser = _fake_playwright(has_widget=False)

    with patch.object(web_captcha, "async_playwright", return_value=pw_factory):
        result, screenshot = await web_captcha.open_for("u1", "https://hh.ru/account/captcha", [])

    assert result == "cleared"
    assert screenshot is None
    await web_captcha.close_for("u1")


async def test_open_for_returns_token_dead_on_login_wall():
    from app.hh import web_captcha

    web_captcha._sessions.clear()
    pw_factory, page, context, browser = _fake_playwright(
        page_url="https://hh.ru/account/login", has_widget=False
    )

    with patch.object(web_captcha, "async_playwright", return_value=pw_factory):
        result, screenshot = await web_captcha.open_for("u1", "https://hh.ru/account/captcha", [])

    assert result == "token_dead"
    assert screenshot is None
    await web_captcha.close_for("u1")


async def test_submit_for_wrong_answer_returns_new_screenshot():
    from app.hh import web_captcha

    web_captcha._sessions.clear()
    pw_factory, page, context, browser = _fake_playwright(has_widget=True)

    with patch.object(web_captcha, "async_playwright", return_value=pw_factory):
        await web_captcha.open_for("u1", "https://hh.ru/account/captcha", [])
        result, screenshot = await web_captcha.submit_for("u1", "wrong-guess")

    assert result == "captcha"
    assert screenshot == b"PNGDATA"
    page.fill.assert_called_once()
    page.keyboard.press.assert_called_once_with("Enter")
    await web_captcha.close_for("u1")


async def test_submit_for_correct_answer_returns_cleared():
    from app.hh import web_captcha

    web_captcha._sessions.clear()
    pw_factory, page, context, browser = _fake_playwright(has_widget=True)

    with patch.object(web_captcha, "async_playwright", return_value=pw_factory):
        await web_captcha.open_for("u1", "https://hh.ru/account/captcha", [])
        page.wait_for_selector = AsyncMock(side_effect=TimeoutError("gone"))
        result, screenshot = await web_captcha.submit_for("u1", "right-answer")

    assert result == "cleared"
    assert screenshot is None
    await web_captcha.close_for("u1")


async def test_cookies_for_returns_context_cookies():
    from app.hh import web_captcha

    web_captcha._sessions.clear()
    pw_factory, page, context, browser = _fake_playwright(has_widget=True)

    with patch.object(web_captcha, "async_playwright", return_value=pw_factory):
        await web_captcha.open_for("u1", "https://hh.ru/account/captcha", [])
        cookies = await web_captcha.cookies_for("u1")

    assert cookies == [{"name": "a", "value": "b"}]
    await web_captcha.close_for("u1")


async def test_close_for_releases_semaphore_and_removes_session():
    from app.hh import web_captcha

    web_captcha._sessions.clear()
    pw_factory, page, context, browser = _fake_playwright(has_widget=True)

    with patch.object(web_captcha, "async_playwright", return_value=pw_factory):
        await web_captcha.open_for("u1", "https://hh.ru/account/captcha", [])
        assert "u1" in web_captcha._sessions
        await web_captcha.close_for("u1")

    assert "u1" not in web_captcha._sessions
    browser.close.assert_called_once()


async def test_open_for_raises_at_capacity_when_semaphore_exhausted():
    from app.hh import web_captcha

    web_captcha._sessions.clear()
    pw_factory, page, context, browser = _fake_playwright(has_widget=True)

    with patch.object(web_captcha, "async_playwright", return_value=pw_factory):
        for i in range(web_captcha.MAX_CONCURRENT_CAPTCHA_BROWSERS):
            await web_captcha.open_for(f"u{i}", "https://hh.ru/account/captcha", [])

        with pytest.raises(web_captcha.AtCapacity):
            await web_captcha.open_for("u-overflow", "https://hh.ru/account/captcha", [])

        for i in range(web_captcha.MAX_CONCURRENT_CAPTCHA_BROWSERS):
            await web_captcha.close_for(f"u{i}")
```

- [ ] **Step 2: Run to confirm they fail**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_web_captcha.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.hh.web_captcha'`.

- [ ] **Step 3: Implement `app/hh/web_captcha.py`**

```python
"""Solves hh's own image captcha (the same widget authorize.py already
handles during OAuth login) against the worker's own stored web session —
not the user's personal browser, which holds a different cookie jar and
never actually clears the wall the worker is stuck behind.

One live headless Chromium per captcha-walled user, held in this module's
process-local registry for the duration of the pause (app/worker/runner.py
owns when to open/close it). Capped globally so N simultaneous captchas
can't spin unbounded browsers on one host.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.hh.authorize import SEL_CAPTCHA_IMAGE, SEL_CAPTCHA_INPUT

logger = logging.getLogger(__name__)

# ponytail: fixed global cap, not measured against real Chromium memory/CPU
# cost — tune (or split per-plan/tier) once real concurrent-captcha usage is
# observed.
MAX_CONCURRENT_CAPTCHA_BROWSERS = 4
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CAPTCHA_BROWSERS)


class AtCapacity(Exception):
    """No free captcha-browser slot right now — caller should back off and retry."""


@dataclass
class _Session:
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page


_sessions: dict[str, _Session] = {}


async def _read_challenge(page: Page) -> tuple[str, bytes | None]:
    """hh answers one of three ways once we're on/near /account/captcha:
    still logged in but blocked (captcha widget), a login wall (dead
    session), or nothing at all (the wall already lifted)."""
    if "/account/login" in (page.url or ""):
        return "token_dead", None
    try:
        await page.wait_for_selector(SEL_CAPTCHA_IMAGE, timeout=3000, state="visible")
    except Exception:
        return "cleared", None
    screenshot = await page.locator(SEL_CAPTCHA_IMAGE).screenshot()
    return "captcha", screenshot


async def open_for(user_id: str, challenge_url: str, cookies: list[dict]) -> tuple[str, bytes | None]:
    """Launch a headless Chromium loaded with `cookies`, navigate to
    challenge_url, report what's there. Raises AtCapacity if the global
    semaphore is exhausted — caller should back off and retry later."""
    if _semaphore.locked():
        raise AtCapacity(user_id)
    await _semaphore.acquire()
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=True)
        device = pw.devices["Galaxy A55"]
        context = await browser.new_context(**device)
        await context.add_cookies(cookies)
        page = await context.new_page()
        _sessions[user_id] = _Session(playwright=pw, browser=browser, context=context, page=page)
    except Exception:
        await pw.stop()
        _semaphore.release()
        raise

    await page.goto(challenge_url, timeout=30000, wait_until="load")
    return await _read_challenge(page)


async def submit_for(user_id: str, solution: str) -> tuple[str, bytes | None]:
    """Type the answer into the open session's captcha input and re-read."""
    page = _sessions[user_id].page
    await page.fill(SEL_CAPTCHA_INPUT, solution)
    await page.keyboard.press("Enter")
    await page.wait_for_load_state("load", timeout=15000)
    return await _read_challenge(page)


async def cookies_for(user_id: str) -> list[dict]:
    """Refreshed cookies from the open session — call only after "cleared"."""
    return await _sessions[user_id].context.cookies()


async def close_for(user_id: str) -> None:
    sess = _sessions.pop(user_id, None)
    if not sess:
        return
    try:
        await sess.browser.close()
    finally:
        await sess.playwright.stop()
        _semaphore.release()
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_web_captcha.py -v`
Expected: all 8 PASS.

- [ ] **Step 5: Add `web_captcha._sessions` to the conftest cache-reset fixture**

In `backend/tests/conftest.py`, extend `_clear_process_caches`:

```python
@pytest.fixture(autouse=True)
def _clear_process_caches():
    def _clear():
        from app.api import deps
        from app.hh import web, web_captcha
        from app.services import form_filler, hh_credentials, notifications
        from app.worker import recruiter_poll

        form_filler._sessions.clear()
        hh_credentials._clients.clear()
        deps._token_cache.clear()
        notifications._once_sent.clear()
        recruiter_poll._states_cache.clear()
        web._last_request_at.clear()
        web_captcha._sessions.clear()

    _clear()
    yield
    _clear()
```

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/ -q --ignore=tests/integration --ignore=tests/e2e`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/hh/web_captcha.py backend/tests/test_web_captcha.py backend/tests/conftest.py
git commit -m "feat: add web_captcha — Playwright-driven hh captcha solving over stored cookies

Reuses authorize.py's captcha selectors and device profile against a
fresh headless browser loaded with the worker's own stored web session
cookies, capped by a global semaphore so many simultaneous captchas
can't spin unbounded Chromium instances."
```

---

### Task 7: `runner.py` — `paused_captcha` drives the real solve, polling the DB

**Files:**
- Modify: `backend/app/worker/runner.py`
- Test: `backend/tests/test_runner.py`

**Interfaces:**
- Consumes: `web_captcha.open_for/submit_for/cookies_for/close_for/AtCapacity` (Task 6), `form_filler.load_web_cookies` (Task 5), `captcha_service.get_pending/attach_screenshot/get_solution/clear_solution/mark_solved` (Task 4 + existing), `hh_auth._persist_web_session_only` (existing).
- Produces: `RunnerHandle` loses `captcha_event`; `WorkerRegistry` loses `resume_captcha`. Nothing new is added to either — the API layer never reaches into the registry for this flow (Task 8 talks to the database instead).

- [ ] **Step 1: Delete the now-obsolete `_probe_me` tests first**

In `backend/tests/test_runner.py`, delete these four tests entirely (they test `_probe_me`, which this task removes): `test_probe_me_ok`, `test_probe_me_transient_keeps_polling`, `test_probe_me_dead_web_session_is_terminal`, `test_probe_me_no_stored_session_is_terminal`.

- [ ] **Step 2: Replace `test_registry_resume_captcha` (the method it tests is being deleted, not repurposed)**

Delete `test_registry_resume_captcha` from `backend/tests/test_runner.py`. There is no replacement registry method to test — Task 8 confirms `/api/captcha/{id}/solve` writes the database directly, no registry call involved.

- [ ] **Step 3: Write the new failing tests for the rewritten pause loop**

Append to `backend/tests/test_runner.py`:

**Important:** `_run_paused_captcha` decides whether to (re)open a browser by checking the real
`web_captcha._sessions` dict (`if user_id not in web_captcha._sessions:`). Since these tests mock
out `web_captcha.open_for`/`close_for` entirely (no real Playwright), the fakes below must mutate
`runner.web_captcha._sessions` themselves to keep that dict truthful — otherwise the loop thinks no
browser is ever open and re-runs the open branch (including `get_pending`/`load_web_cookies`) on
every single tick instead of once.

```python
async def test_paused_captcha_opens_browser_and_resumes_on_cleared():
    """A pending captcha_requests row with a solution ready should drive
    open_for → submit_for → "cleared" → persisted cookies → running."""
    from app.worker import runner

    runner.reset_registry()
    runner.web_captcha._sessions.clear()

    handle = runner.RunnerHandle(user_id="u1")
    handle.state = "paused_captcha"

    persisted = []

    async def _fake_load_cookies(user_id):
        return [{"name": "a", "value": "b"}]

    async def _fake_get_pending(user_id):
        return [{"id": "req1", "captcha_url": "https://hh.ru/account/captcha?state=x"}]

    async def _fake_open_for(user_id, challenge_url, cookies):
        runner.web_captcha._sessions[user_id] = object()
        return "captcha", b"PNG"

    async def _fake_attach(request_id, png):
        pass

    async def _fake_get_solution(request_id):
        return "AB12"

    async def _fake_clear_solution(request_id):
        pass

    async def _fake_submit_for(user_id, solution):
        return "cleared", None

    async def _fake_cookies_for(user_id):
        return [{"name": "fresh", "value": "cookie"}]

    async def _fake_close_for(user_id):
        runner.web_captcha._sessions.pop(user_id, None)

    def _fake_persist(user_id, cookies):
        persisted.append((user_id, cookies))

    async def _fake_mark_solved(user_id):
        pass

    async def _fake_notify(user_id, type_, payload=None):
        pass

    async def _fake_hb(*a, **k):
        pass

    with (
        patch.object(runner.form_filler, "load_web_cookies", new=_fake_load_cookies),
        patch.object(runner.captcha_service, "get_pending", new=_fake_get_pending),
        patch.object(runner.web_captcha, "open_for", new=_fake_open_for),
        patch.object(runner.captcha_service, "attach_screenshot", new=_fake_attach),
        patch.object(runner.captcha_service, "get_solution", new=_fake_get_solution),
        patch.object(runner.captcha_service, "clear_solution", new=_fake_clear_solution),
        patch.object(runner.web_captcha, "submit_for", new=_fake_submit_for),
        patch.object(runner.web_captcha, "cookies_for", new=_fake_cookies_for),
        patch.object(runner.web_captcha, "close_for", new=_fake_close_for),
        patch.object(runner.captcha_service, "mark_solved", new=_fake_mark_solved),
        patch.object(runner, "notify", new=_fake_notify),
        patch.object(runner, "heartbeat", new=_fake_hb),
        patch("app.services.hh_auth._persist_web_session_only", side_effect=_fake_persist),
        patch.object(runner, "CAPTCHA_POLL_S", 0),
    ):
        await runner._run_paused_captcha(handle)

    assert handle.state == "running"
    assert persisted == [("u1", [{"name": "fresh", "value": "cookie"}])]


async def test_paused_captcha_wrong_answer_loops_without_leaving_pause():
    from app.worker import runner

    runner.reset_registry()
    runner.web_captcha._sessions.clear()

    handle = runner.RunnerHandle(user_id="u1")
    handle.state = "paused_captcha"

    submit_calls = []
    solutions = iter(["wrong-once", "right-answer"])
    results = iter([("captcha", b"PNG2"), ("cleared", None)])

    async def _fake_load_cookies(user_id):
        return []

    async def _fake_get_pending(user_id):
        return [{"id": "req1", "captcha_url": "https://hh.ru/account/captcha"}]

    async def _fake_open_for(user_id, challenge_url, cookies):
        runner.web_captcha._sessions[user_id] = object()
        return "captcha", b"PNG1"

    async def _fake_attach(request_id, png):
        pass

    async def _fake_get_solution(request_id):
        return next(solutions, None)

    async def _fake_clear_solution(request_id):
        pass

    async def _fake_submit_for(user_id, solution):
        submit_calls.append(solution)
        return next(results)

    async def _fake_cookies_for(user_id):
        return []

    async def _fake_close_for(user_id):
        runner.web_captcha._sessions.pop(user_id, None)

    async def _fake_mark_solved(user_id):
        pass

    async def _fake_notify(user_id, type_, payload=None):
        pass

    async def _fake_hb(*a, **k):
        pass

    with (
        patch.object(runner.form_filler, "load_web_cookies", new=_fake_load_cookies),
        patch.object(runner.captcha_service, "get_pending", new=_fake_get_pending),
        patch.object(runner.web_captcha, "open_for", new=_fake_open_for),
        patch.object(runner.captcha_service, "attach_screenshot", new=_fake_attach),
        patch.object(runner.captcha_service, "get_solution", new=_fake_get_solution),
        patch.object(runner.captcha_service, "clear_solution", new=_fake_clear_solution),
        patch.object(runner.web_captcha, "submit_for", new=_fake_submit_for),
        patch.object(runner.web_captcha, "cookies_for", new=_fake_cookies_for),
        patch.object(runner.web_captcha, "close_for", new=_fake_close_for),
        patch.object(runner.captcha_service, "mark_solved", new=_fake_mark_solved),
        patch.object(runner, "notify", new=_fake_notify),
        patch.object(runner, "heartbeat", new=_fake_hb),
        patch.object(runner, "CAPTCHA_POLL_S", 0),
    ):
        await runner._run_paused_captcha(handle)

    assert submit_calls == ["wrong-once", "right-answer"]
    assert handle.state == "running"


async def test_paused_captcha_idle_timeout_closes_browser_without_ending_pause():
    """No solution ever arrives for CAPTCHA_BROWSER_IDLE_TIMEOUT_S — the
    browser must free its slot on its own; the pause itself must not end
    (no solve, no resume) — only the test's own sentinel in _fake_close_for
    ends the loop, so a pass here proves the close happened without also
    proving a real resume happened."""
    from app.worker import runner

    runner.reset_registry()
    runner.web_captcha._sessions.clear()

    handle = runner.RunnerHandle(user_id="u1")
    handle.state = "paused_captcha"

    async def _fake_load_cookies(user_id):
        return []

    async def _fake_get_pending(user_id):
        return [{"id": "req1", "captcha_url": "https://hh.ru/account/captcha"}]

    async def _fake_open_for(user_id, challenge_url, cookies):
        runner.web_captcha._sessions[user_id] = object()
        return "captcha", b"PNG"

    async def _fake_attach(request_id, png):
        pass

    async def _fake_get_solution(request_id):
        return None  # never solved

    closed = []

    async def _fake_close_for(user_id):
        closed.append(user_id)
        runner.web_captcha._sessions.pop(user_id, None)
        handle.state = "stopped"  # test sentinel: end the loop once we've seen one close

    with (
        patch.object(runner.form_filler, "load_web_cookies", new=_fake_load_cookies),
        patch.object(runner.captcha_service, "get_pending", new=_fake_get_pending),
        patch.object(runner.web_captcha, "open_for", new=_fake_open_for),
        patch.object(runner.captcha_service, "attach_screenshot", new=_fake_attach),
        patch.object(runner.captcha_service, "get_solution", new=_fake_get_solution),
        patch.object(runner.web_captcha, "close_for", new=_fake_close_for),
        patch.object(runner, "CAPTCHA_POLL_S", 0.001),
        patch.object(runner, "CAPTCHA_BROWSER_IDLE_TIMEOUT_S", 0.002),
    ):
        await runner._run_paused_captcha(handle)

    assert closed == ["u1"]
    assert handle.state == "stopped"  # test's own sentinel, not a captcha resolution
```

- [ ] **Step 4: Run to confirm they fail**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_runner.py -k paused_captcha -v`
Expected: FAIL — `runner._run_paused_captcha` doesn't exist yet (the pause logic is currently inline in `_run_loop`, not its own function).

- [ ] **Step 5: Extract the pause handling into `_run_paused_captcha` and rewrite it**

This step has several parts to the same file, `backend/app/worker/runner.py`.

**5a. Imports** — replace the current import block:

```python
from app.hh import errors as hh_errors
from app.hh import web as hh_web
from app.services import apply as apply_service
from app.services import captcha as captcha_service
from app.services import plan as plan_service
from app.services import worker_control
from app.services.form_filler import WebSessionExpired
from app.services.hh_credentials import mark_invalid
from app.services.notifications import notify
```

with:

```python
from app.hh import errors as hh_errors
from app.hh import web_captcha
from app.services import apply as apply_service
from app.services import captcha as captcha_service
from app.services import form_filler
from app.services import plan as plan_service
from app.services import worker_control
from app.services.notifications import notify
```

(`hh_web`, `WebSessionExpired`, `mark_invalid` were only used by `_probe_me`, deleted in 5c — dropped. `form_filler` module import added since `load_web_cookies` is called as `form_filler.load_web_cookies` in the tests above. `web_captcha` added.)

**5b. Constants** — replace:

```python
# Plan-B captcha poll interval (seconds) — re-probe GET /me while paused.
CAPTCHA_POLL_S = 5
```

with:

```python
# Plan-B captcha poll interval (seconds) — the API and worker are separate
# processes with no shared memory, so the typed solution can only cross that
# boundary through the database; this is how often the paused loop checks.
CAPTCHA_POLL_S = 5

# How long to keep a captcha browser open with no solution submitted before
# freeing its semaphore slot. Reopening on the next tick also re-screenshots,
# which catches a wall that quietly cleared on its own.
CAPTCHA_BROWSER_IDLE_TIMEOUT_S = 5 * 60

# Backoff before retrying open_for() after AtCapacity.
CAPTCHA_OPEN_RETRY_S = 15
```

**5c. Delete `_probe_me`** — remove the entire function (currently ~lines 155-178):

```python
async def _probe_me(user_id: str) -> str:
    """Probe GET /me to detect whether the hh captcha lifted.
    ...
    """
    try:
        ...
```

through its closing `return "captcha"` line.

**5d. Extract the pause handling into `_run_paused_captcha`** — the current `_run_loop` has this inline at its top (currently lines 218-262):

```python
        # Captcha pause — wait until external resume sets event.
        if handle.state == "paused_captcha":
            handle.next_run_at = None
            while handle.state == "paused_captcha":
                try:
                    await asyncio.wait_for(
                        handle.captcha_event.wait(), timeout=CAPTCHA_POLL_S
                    )
                except TimeoutError:
                    pass
                handle.captcha_event.clear()
                if handle.state != "paused_captcha":
                    break
                result = await _probe_me(user_id)
                if result == "ok":
                    await captcha_service.mark_solved(user_id)
                    await notify(user_id, "captcha", {"resolved": True})
                    handle.state = "running"
                    await _hb()
                    logger.info("user %s: captcha cleared — resuming", user_id)
                elif result == "token_dead":
                    handle.state = "stopped"
                    handle.last_error = "hh token dead — reconnect required"
                    await notify(user_id, "token_dead", {})
                    await notify(user_id, "worker_stop", {"reason": "token_dead"})
                    await _disable_worker(user_id)
                    await _hb()
                    logger.error(
                        "user %s: token dead during captcha probe — stopping", user_id
                    )
                    return
                elif result == "banned":
                    handle.state = "stopped"
                    handle.last_error = "hh account banned"
                    await notify(user_id, "account_banned", {})
                    await notify(user_id, "worker_stop", {"reason": "account_banned"})
                    await _disable_worker(user_id)
                    await _hb()
                    logger.error(
                        "user %s: account banned during captcha probe — stopping", user_id
                    )
                    return
                # "captcha" → keep polling
            if handle.state == "stopped":
                return
```

Replace that whole block with a single call:

```python
        if handle.state == "paused_captcha":
            await _run_paused_captcha(handle)
            if handle.state == "stopped":
                return
```

And define `_run_paused_captcha` as a new top-level function, placed right before `_run_loop` (so it's defined before use — Python doesn't strictly require this for module-level functions called at runtime, but match the file's existing top-to-bottom reading order):

```python
async def _stop_worker_token_dead(handle: RunnerHandle, context: str) -> None:
    user_id = handle.user_id
    handle.state = "stopped"
    handle.last_error = "hh token dead — reconnect required"
    await notify(user_id, "token_dead", {})
    await notify(user_id, "worker_stop", {"reason": "token_dead"})
    await _disable_worker(user_id)
    await heartbeat(
        user_id, state="stopped", queued=0, next_run_at=None, last_error=handle.last_error
    )
    logger.error("user %s: token dead (%s) — stopping", user_id, context)


async def _resume_from_captcha(handle: RunnerHandle) -> None:
    user_id = handle.user_id
    from app.services.hh_auth import _persist_web_session_only

    cookies = await web_captcha.cookies_for(user_id)
    await web_captcha.close_for(user_id)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _persist_web_session_only, user_id, cookies)
    await captcha_service.mark_solved(user_id)
    await notify(user_id, "captcha", {"resolved": True})
    handle.state = "running"
    await heartbeat(
        user_id,
        state="running",
        queued=0,
        next_run_at=handle.next_run_at,
        last_error=None,
    )
    logger.info("user %s: captcha cleared — resuming", user_id)


async def _run_paused_captcha(handle: RunnerHandle) -> None:
    """Own the captcha browser for the duration of one pause: open it, show
    the challenge, poll the database for a typed solution (the API process
    that receives it has no other way to reach this one), submit, repeat on
    a wrong answer, resume on a right one."""
    user_id = handle.user_id
    handle.next_run_at = None
    request_id: str | None = None
    idle_ticks = 0

    try:
        while handle.state == "paused_captcha":
            if user_id not in web_captcha._sessions:
                try:
                    cookies = await form_filler.load_web_cookies(user_id)
                except ValueError:
                    await _stop_worker_token_dead(handle, "no stored web session")
                    return

                pending = await captcha_service.get_pending(user_id)
                request_id = pending[0]["id"] if pending else None
                challenge_url = (
                    (pending[0].get("captcha_url") if pending else None)
                    or "https://hh.ru/account/captcha"
                )
                try:
                    result, screenshot = await web_captcha.open_for(user_id, challenge_url, cookies)
                except web_captcha.AtCapacity:
                    await asyncio.sleep(CAPTCHA_OPEN_RETRY_S)
                    continue

                if result == "token_dead":
                    await web_captcha.close_for(user_id)
                    await _stop_worker_token_dead(handle, "captcha page")
                    return
                if result == "cleared":
                    await _resume_from_captcha(handle)
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
                    await web_captcha.close_for(user_id)
                continue

            await captcha_service.clear_solution(request_id)
            result, screenshot = await web_captcha.submit_for(user_id, solution)
            if result == "captcha":
                if request_id:
                    await captcha_service.attach_screenshot(request_id, screenshot)
                idle_ticks = 0
                continue
            if result == "token_dead":
                await web_captcha.close_for(user_id)
                await _stop_worker_token_dead(handle, "after captcha submit")
                return
            await _resume_from_captcha(handle)
    finally:
        if user_id in web_captcha._sessions:
            await web_captcha.close_for(user_id)
```

**5e. Drop the `captcha_event` reset in the apply-status handler** — in `_run_loop`, the `elif status == "captcha":` branch currently reads:

```python
        elif status == "captcha":
            handle.state = "paused_captcha"
            handle.captcha_event.clear()
            handle.last_error = f"captcha on vacancy {job.vacancy_id}"
            logger.warning("user %s: captcha — pausing", user_id)
            await notify(user_id, "captcha", {"vacancy_id": job.vacancy_id})
            await _hb()
```

Change to:

```python
        elif status == "captcha":
            handle.state = "paused_captcha"
            handle.last_error = f"captcha on vacancy {job.vacancy_id}"
            logger.warning("user %s: captcha — pausing", user_id)
            await notify(user_id, "captcha", {"vacancy_id": job.vacancy_id})
            await _hb()
```

**5f. Remove the `captcha_event` field from `RunnerHandle`** — currently:

```python
    captcha_event: asyncio.Event = field(default_factory=asyncio.Event)
```

Delete this line entirely from the `RunnerHandle` dataclass.

**5g. Remove `WorkerRegistry.resume_captcha`** — delete the method entirely:

```python
    def resume_captcha(self, user_id: str) -> bool:
        handle = self._handles.get(user_id)
        if not handle or handle.state != "paused_captcha":
            return False
        handle.captcha_event.set()
        return True
```

- [ ] **Step 6: Run the new tests to confirm they pass**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/test_runner.py -k paused_captcha -v`
Expected: 3 PASS.

- [ ] **Step 7: Run the full backend test suite**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/ -q --ignore=tests/integration --ignore=tests/e2e`
Expected: all pass. Pay particular attention to any other test in `test_runner.py` that referenced `handle.captcha_event` or `registry.resume_captcha` beyond the ones already deleted in Steps 1-2 — grep first: `grep -rn "captcha_event\|resume_captcha" backend/tests/ backend/app/` should return nothing after this task.

- [ ] **Step 8: Commit**

```bash
git add backend/app/worker/runner.py backend/tests/test_runner.py
git commit -m "feat: runner drives real captcha solving via a Playwright browser, polling the DB

paused_captcha now opens a headless browser holding the account's own
cookies (app.hh.web_captcha), screenshots hh's real challenge, and
polls captcha_requests.solution for the answer the user types into
the dashboard — the API process that receives it can't reach this
one's memory directly. Retires the _probe_me HTTP-probe auto-clear
mechanism (its health-check duty moves into web_captcha.open_for) and
the dead WorkerRegistry.resume_captcha (confirmed uncalled outside its
own test — the API has no reachable registry for this flow)."
```

---

### Task 8: `app/api/captcha.py` — `/solve` writes the typed answer

**Files:**
- Modify: `backend/app/api/captcha.py`

**Interfaces:**
- Consumes: `captcha_service.submit_solution(user_id, solution)` (Task 4).
- Produces: `POST /api/captcha/{request_id}/solve` now requires a JSON body `{"solution": "<text>"}`.

There is no dedicated test file for this router today (`test_captcha.py` tests the service layer only) — the endpoint is a thin delegation, consistent with the existing `/pending`/`/dismiss` routes which also have no dedicated API-level test. No new test file for this task.

- [ ] **Step 1: Update the router**

The current `backend/app/api/captcha.py` reads:

```python
"""Captcha handoff endpoints (plan B).

The worker handles one captcha at a time per user, so both actions clear that
user's pending rows; `{request_id}` is kept for REST shape only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.services import captcha as captcha_service

router = APIRouter(prefix="/api/captcha", tags=["captcha"])


class RecheckResponse(BaseModel):
    rechecking: bool


class DismissResponse(BaseModel):
    dismissed: bool


@router.get("/pending")
async def pending(user_id: str = Depends(get_current_user)) -> list[dict]:
    return await captcha_service.get_pending(user_id)


@router.post("/{request_id}/solve", response_model=RecheckResponse)
async def solve(
    request_id: str, user_id: str = Depends(get_current_user)
) -> RecheckResponse:
    # The runner (worker container) re-probes GET /me on its own poll cycle and
    # resumes once hh lifts the captcha — this just clears the pending row.
    await captcha_service.mark_solved(user_id)
    return RecheckResponse(rechecking=True)


@router.post("/{request_id}/dismiss", response_model=DismissResponse)
async def dismiss(
    request_id: str, user_id: str = Depends(get_current_user)
) -> DismissResponse:
    # Только убирает окно: воркер остаётся на паузе и сам продолжит, когда hh
    # снимет капчу. Кнопка «закрыть» не должна выключать автоотклик целиком.
    await captcha_service.mark_solved(user_id)
    return DismissResponse(dismissed=True)
```

Change the `solve` endpoint (only that function — `dismiss` is unchanged, it already just hides the modal while the worker keeps working the row on its own):

```python
"""Captcha handoff endpoints (plan B).

The worker handles one captcha at a time per user, so both actions clear that
user's pending rows; `{request_id}` is kept for REST shape only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.services import captcha as captcha_service

router = APIRouter(prefix="/api/captcha", tags=["captcha"])


class RecheckResponse(BaseModel):
    rechecking: bool


class DismissResponse(BaseModel):
    dismissed: bool


class SolveRequest(BaseModel):
    solution: str


@router.get("/pending")
async def pending(user_id: str = Depends(get_current_user)) -> list[dict]:
    return await captcha_service.get_pending(user_id)


@router.post("/{request_id}/solve", response_model=RecheckResponse)
async def solve(
    request_id: str, body: SolveRequest, user_id: str = Depends(get_current_user)
) -> RecheckResponse:
    # The worker (a separate process — no in-memory channel reaches it from
    # here) polls captcha_requests.solution on its own cycle and submits it
    # into the live browser holding the account's session.
    await captcha_service.submit_solution(user_id, body.solution)
    return RecheckResponse(rechecking=True)


@router.post("/{request_id}/dismiss", response_model=DismissResponse)
async def dismiss(
    request_id: str, user_id: str = Depends(get_current_user)
) -> DismissResponse:
    # Только убирает окно: воркер остаётся на паузе и сам продолжит работать
    # над капчей (переоткрывая браузер по таймауту простоя). Кнопка «закрыть»
    # не должна выключать автоотклик целиком.
    await captcha_service.mark_solved(user_id)
    return DismissResponse(dismissed=True)
```

- [ ] **Step 2: Sanity-check the app still imports cleanly**

Run: `cd backend && source .venv/bin/activate && python -c "from app.main import app; print('ok')"`
Expected: `ok` (catches any syntax error or import cycle immediately, cheaper than booting uvicorn).

- [ ] **Step 3: Run the full backend test suite**

Run: `cd backend && source .venv/bin/activate && python -m pytest tests/ -q --ignore=tests/integration --ignore=tests/e2e`
Expected: all pass (no existing test exercised the old no-body `/solve` contract, so nothing should break).

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/captcha.py
git commit -m "feat: POST /api/captcha/{id}/solve accepts the typed captcha answer"
```

---

### Task 9: `frontend/src/components/captcha-modal.tsx` — real input, no more fake copy

**Files:**
- Modify: `frontend/src/components/captcha-modal.tsx`

**Interfaces:**
- Consumes: `POST /api/captcha/{id}/solve` now expecting `{ solution: string }` (Task 8).

No test framework covers this component today (`npm test` in this repo runs `lib/` pure-function unit tests, not component tests — check `frontend/package.json`'s `test` script if unsure; component-level testing is out of scope for this task, matching existing coverage). Verify manually per Step 4.

- [ ] **Step 1: Add solution input state and update `handleSolve`**

In `frontend/src/components/captcha-modal.tsx`, add a `solution` state near the top of the component (right after the existing `useState` calls):

```tsx
export default function CaptchaModal() {
  const [pending, setPending] = useState<CaptchaRequest | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [forcedOpen, setForcedOpen] = useState(false);
  const [solution, setSolution] = useState("");
  const supabase = useMemo(() => createClient(), []);
```

Replace `handleSolve`:

```tsx
  async function handleSolve() {
    if (!pending || !solution.trim()) return;
    try {
      await apiFetch(`/api/captcha/${pending.id}/solve`, {
        method: "POST",
        body: JSON.stringify({ solution: solution.trim() }),
      });
      setSolution("");
    } catch {
      /* best-effort */
    }
  }
```

Also clear `solution` when the modal closes via dismiss — update `handleDismiss`:

```tsx
  async function handleDismiss() {
    const id = pending?.id;
    setPending(null);
    setImageUrl(null);
    setForcedOpen(false);
    setSolution("");
    if (!id) return;
    try {
      await apiFetch(`/api/captcha/${id}/dismiss`, { method: "POST" });
    } catch {
      /* best-effort */
    }
  }
```

- [ ] **Step 2: Update the copy and add the input field**

Replace the header text block:

```tsx
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 18, fontWeight: 700 }}>hh просит решить капчу</div>
            <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 2 }}>
              Бот поставлен на паузу. Реши капчу на hh — worker подхватит сам.
            </div>
          </div>
```

with:

```tsx
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 18, fontWeight: 700 }}>hh просит решить капчу</div>
            <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 2 }}>
              Бот поставлен на паузу. Введи текст с картинки — автоотклик продолжит сам.
            </div>
          </div>
```

Add the input field right after the image block (after the `imageUrl ? (...) : (...)` block, before the buttons row):

```tsx
        <input
          type="text"
          value={solution}
          onChange={(e) => setSolution(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSolve();
          }}
          placeholder="Текст с картинки"
          autoFocus
          style={{
            width: "100%",
            padding: "10px 14px",
            borderRadius: 12,
            border: "1px solid var(--line)",
            fontSize: 14,
            marginBottom: 12,
            background: "var(--bg-deep)",
            color: "var(--ink)",
          }}
        />

        <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          <Btn kind="primary" onClick={handleSolve}>
            отправить
          </Btn>
          <Btn kind="ghost" onClick={handleDismiss}>
            закрыть
          </Btn>
        </div>
```

This replaces the existing buttons row, which currently reads:

```tsx
        <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          {pending.captcha_url && (
            <a
              href={pending.captcha_url}
              target="_blank"
              rel="noreferrer"
              style={{
                background: "var(--ink)",
                color: "#fff",
                padding: "10px 16px",
                borderRadius: 999,
                fontSize: 14,
                fontWeight: 600,
                textDecoration: "none",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              открыть на hh <IExternal size={13} />
            </a>
          )}
          <Btn kind="ghost" onClick={handleSolve}>
            я решил, проверить
          </Btn>
          <Btn kind="ghost" onClick={handleDismiss}>
            закрыть
          </Btn>
        </div>
```

The `открыть на hh` external link is dropped entirely — solving now happens in-app against the worker's own session, so sending the user to their own separate hh.ru login does nothing useful. Check whether `IExternal` is still used elsewhere in this file after removing it (`grep -n "IExternal" frontend/src/components/captcha-modal.tsx`); if not, remove it from the `icons` import at the top of the file:

```tsx
import { IClose, IExternal, IShield } from "@/components/otclick/icons";
```

becomes:

```tsx
import { IClose, IShield } from "@/components/otclick/icons";
```

- [ ] **Step 3: Verify `Btn`'s `kind` prop supports `"primary"`**

Run: `grep -n "kind" frontend/src/components/otclick/ui.tsx | head -20`
If `"primary"` isn't one of `Btn`'s accepted `kind` values, use whichever accent variant that file defines for a primary action instead (check the `Btn` component's prop union type in `ui.tsx`) — match it exactly rather than guessing a string.

- [ ] **Step 4: Type-check and manually verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

Run: `cd frontend && npm run dev`, then in a browser open the dashboard, and use `Skill(claude-in-chrome)` or manual devtools to insert a test row into `captcha_requests` (via the local Supabase stack) with `solved=false` and a `storage_path` pointing at any object in the `captcha-screenshots` bucket, confirm: the modal shows the image, the input accepts text, pressing Enter or "отправить" calls `POST /api/captcha/{id}/solve` with `{"solution": "..."}` in the request body (check the Network tab), and "закрыть" still calls `/dismiss` and hides the modal.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/captcha-modal.tsx
git commit -m "feat: captcha modal takes the real answer instead of a fake 'go solve it' link

The old copy sent users to solve hh's captcha in their own logged-in
browser, which never affected the worker's separate stored session.
The modal now posts the typed answer to /api/captcha/{id}/solve,
which the worker (app.hh.web_captcha) types into the same session
that's actually blocked."
```

---

### Task 10: Rebuild and smoke-test against the local stack

**Files:** none (operational verification only)

- [ ] **Step 1: Rebuild the backend image**

Run: `cd /Users/nurma/vscode_projects/AIautoclicker && docker compose build api worker`
Expected: build succeeds.

- [ ] **Step 2: Rebuild the frontend image**

Run: `docker compose build frontend`
Expected: build succeeds (Next.js bakes env at build time, but no env vars changed here — this rebuild only picks up the `captcha-modal.tsx` change).

- [ ] **Step 3: Restart all three**

Run: `docker compose up -d api worker frontend`
Expected: all three report healthy/started in `docker compose ps`.

- [ ] **Step 4: Watch worker logs for a real captcha cycle**

Run: `docker compose logs worker -f --since 1m` in one terminal, trigger or wait for a captcha (or, since the account is currently mid-captcha-storm per the earlier investigation this session, one should appear within a few apply attempts). Confirm the log sequence: `apply: user=... captcha on vacancy fetch` (or `on submit`) → a `POST .../captcha_requests` insert → `runner: user=... vacancy=... status=captcha` → the pause loop opening a browser (no explicit log line exists for this yet — absence of a crash/traceback and a `POST .../captcha_requests?...` PATCH updating `storage_path` shortly after is the signal) → once solved through the dashboard modal, `user %s: captcha cleared — resuming` (from `_resume_from_captcha`'s log line).

- [ ] **Step 5: Confirm via the dashboard**

Open the dashboard in a browser, watch for the captcha modal to appear with a real screenshot (not the old "скриншот грузится…" placeholder or the "реши сам на hh" copy), type the answer from the image, submit, and confirm the worker bar returns to "работает" without manual intervention beyond typing the answer.

This task has no commit — it's verification of Tasks 1-9's combined behavior against the real, currently-captcha-walled account from this session's earlier investigation.
