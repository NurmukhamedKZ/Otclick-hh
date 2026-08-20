# hh Web-Session Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drop the hh OAuth API as the product's data path and serve every job-seeker operation (search, resume list, apply, negotiation state) over the logged-in hh.ru **web session** we already capture during Playwright login.

**Architecture:** The Playwright login still runs and still succeeds — only the `/oauth/authorize` grant is refused (`error=geo_forbidden`, see `docs`/memory). We keep that login, keep `web_cookies_encrypted`, and stop asking for an OAuth code. A new `app/hh/web.py` exposes the handful of operations the app actually needs, each implemented as "GET the hh page → decode the entity-encoded inline JSON → pull the block we need", reusing the parser `form_filler` already ships. Call sites migrate one at a time behind the existing service function signatures, so `runner.py`, the API layer and the frontend do not change.

**Tech Stack:** Python 3.13, `requests` (web session), Playwright (login only), pytest, Supabase.

## Global Constraints

- **No new dependencies.** `requests` + stdlib only; the JSON extraction reuses `form_filler._find_balanced_object` / `_decode_page` (promote them, do not re-implement).
- **No invented endpoints or payloads.** Every request shape in Tasks 3–6 must be copied from a real captured response produced in Task 1. If Task 1 did not capture it, the task is blocked, not guessed.
- **Every hh web response goes through `session_looks_dead()`** and raises `WebSessionExpired` — a logged-out session must surface as the existing `web_session_expired` notification, never as a silent empty result.
- **Service function signatures stay unchanged**: `sync_resumes(user_id)`, `preview_filter(user_id, filter_id)`, `produce_jobs(user_id, agent)`, `apply_one(...)`, `sync_states(user_id, force)`. Only their internals change.
- **`ApplyStatus` literals stay exactly as they are** (`sent`/`form_sent`/`form_pending`/`form_required`/`captcha`/`token_dead`/`account_banned`/`resume_missing`/`vacancy_gone`/…). `apply.RETRYABLE_STATUSES` remains the single source of truth.
- Rate limiting: keep a per-user minimum delay between hh web requests at least as large as `client.DEFAULT_DELAY` (0.345s). Web traffic is more fingerprintable than API traffic, not less.
- Tests are unit-level with mocked HTTP; set env vars before importing `app.*` (see `tests/test_hh_auth.py` header). Register any new process-local cache in `tests/conftest.py`.

## Scope Note

This plan covers one subsystem: the hh data path. Two things are deliberately **out of scope** and should be separate plans if wanted:
- Removing the OAuth code entirely (keep it dormant — it still works from a permitted region, and deleting it destroys the fallback).
- Proxy support (`HH_PROXY`). Only needed if hh also blocks web traffic by IP, which Task 1 will disprove or confirm.

---

### Task 1: Recon — capture the real web payloads

**This task produces evidence, not product code. Tasks 3–6 are blocked until it is done.**

**Files:**
- Create: `backend/scripts/recon_web.py`
- Output (gitignored): `backend/recon_web_out/*.json`

**Interfaces:**
- Produces: captured JSON blocks named `resumes.json`, `vacancy.json`, `negotiations.json`, `apply_no_test.json` under `backend/recon_web_out/`, which Tasks 3–6 read field names from.

- [ ] **Step 1: Write the recon script**

It must reuse the live web session rather than re-login. Read cookies straight out of the DB the same way `form_filler._load_cookies_encrypted` does, build a `requests.Session`, then dump each page's decoded inline JSON.

```python
"""Recon: capture the inline JSON of every hh page the web path will need."""
from __future__ import annotations

import html, json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.form_filler import _find_balanced_object  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "recon_web_out"

PAGES = {
    "resumes":      ("https://hh.ru/applicant/resumes", '"resumeList"'),
    "negotiations": ("https://hh.ru/applicant/negotiations", '"negotiationsList"'),
    "vacancy":      ("https://hh.ru/vacancy/{vacancy_id}", '"vacancyView"'),
}


def dump(session, name, url, marker):
    r = session.get(url, timeout=20)
    text = html.unescape(r.text)
    OUT.joinpath(f"{name}.html").write_text(text, encoding="utf-8")
    i = text.find(marker)
    if i == -1:
        print(f"{name}: MARKER {marker} NOT FOUND (status={r.status_code}) — "
              f"open {name}.html and find the real key")
        return
    blob = _find_balanced_object(text, text.find("{", i))
    OUT.joinpath(f"{name}.json").write_text(blob, encoding="utf-8")
    print(f"{name}: ok, {len(blob)} bytes -> {name}.json")
```

The markers above are **guesses**. When one is not found, the script says so and dumps the HTML; find the real key in the dump and correct the table. That correction is the deliverable.

- [ ] **Step 2: Run it against a live logged-in session**

Run: `cd backend && python scripts/recon_web.py <user_id> <a_vacancy_id_without_a_test>`
Expected: four files in `backend/recon_web_out/`. Any `MARKER NOT FOUND` line must be resolved before continuing.

- [ ] **Step 3: Capture an apply that has no test**

Open a no-test vacancy in the recon browser (`scripts/recon_oauth.py` already logs requests), click «Откликнуться» by hand, and record the exact `POST` to `vacancy_response/popup`: full form body and headers. Save as `recon_web_out/apply_no_test.json`.

This is the single highest-risk unknown in the plan: `form_filler._submit` currently always sends `uidPk`/`guid`/`startTime`/`testRequired`, which only exist when the vacancy has a test. Task 5 needs to know which of those fields hh requires when it does not.

- [ ] **Step 4: Confirm the web path is not geo-blocked**

Verify each captured page returned real content and not a login redirect from the Kazakhstan IP. If any of them is geo-blocked, **stop the plan** and reopen the proxy option — the whole approach rests on web being reachable where OAuth is not.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/recon_web.py .gitignore
git commit -m "chore(hh): recon script for the web-session data path"
```

---

### Task 2: Extract the shared page-JSON parser

**Files:**
- Create: `backend/app/hh/page_json.py`
- Modify: `backend/app/services/form_filler.py` (import from the new module, delete the local copies)
- Test: `backend/tests/test_page_json.py`

**Interfaces:**
- Produces: `find_state(page_html: str, key: str) -> dict` — decodes hh's entity-encoded inline JSON and returns the object stored under `"<key>":`. Raises `ValueError` when absent. Also re-exports `find_balanced_object(text: str, start: int) -> str`.
- Consumes: nothing.

- [ ] **Step 1: Write the failing test**

```python
import html

def test_find_state_reads_entity_encoded_inline_json():
    from app.hh.page_json import find_state

    raw = '<script>window.x = {&#34;vacancySearchResult&#34;:{&#34;totalResults&#34;:229}}</script>'
    assert find_state(raw, "vacancySearchResult") == {"totalResults": 229}


def test_find_state_reads_plain_json_without_double_unescaping():
    from app.hh.page_json import find_state

    raw = '{"vacancySearchResult":{"name":"a &amp; b"}}'
    # Already plain: the literal &amp; must survive, not become "&".
    assert find_state(raw, "vacancySearchResult") == {"name": "a &amp; b"}


def test_find_state_raises_when_key_absent():
    import pytest
    from app.hh.page_json import find_state

    with pytest.raises(ValueError, match="nope"):
        find_state("<html></html>", "nope")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_page_json.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.hh.page_json'`

- [ ] **Step 3: Write the implementation**

Move `_find_balanced_object` verbatim from `form_filler.py`, and generalise `_decode_page` so the "already plain?" probe uses the requested key instead of the hardcoded `vacancyTests` marker.

```python
"""hh serves its page state as entity-encoded inline JSON. One parser for all of it."""
from __future__ import annotations

import html
import json


def find_balanced_object(text: str, obj_start: int) -> str:
    """Return the JSON object substring starting at text[obj_start] == '{'."""
    # (moved verbatim from services/form_filler.py — do not rewrite)


def find_state(page_html: str, key: str) -> dict:
    marker = f'"{key}":'
    if marker not in page_html:
        page_html = html.unescape(page_html)
    i = page_html.find(marker)
    if i == -1:
        raise ValueError(f"{key} not found in page")
    return json.loads(find_balanced_object(page_html, page_html.find("{", i)), strict=False)
```

- [ ] **Step 4: Point form_filler at it**

In `form_filler.py`, delete `_find_balanced_object` and `_decode_page`, and rewrite `_parse_tests` as `find_state(page_html, "vacancyTests")[str(vacancy_id)]`. Keep `extract_xsrf_token` where it is — it parses a bare string, not an object.

- [ ] **Step 5: Run the full suite**

Run: `cd backend && python -m pytest tests -q --ignore=tests/e2e`
Expected: PASS, 339+ tests. The existing `form_filler` tests are the regression net for the move.

- [ ] **Step 6: Commit**

```bash
git add backend/app/hh/page_json.py backend/app/services/form_filler.py backend/tests/test_page_json.py
git commit -m "refactor(hh): one inline-JSON parser for every hh page"
```

---

### Task 3: `hh/web.py` — session + vacancy search

**Files:**
- Create: `backend/app/hh/web.py`
- Test: `backend/tests/test_hh_web.py`

**Interfaces:**
- Consumes: `app.hh.page_json.find_state`; `form_filler.load_web_session`, `session_looks_dead`, `WebSessionExpired`.
- Produces:
  - `async def search_vacancies(user_id: str, params: dict, page: int = 0) -> tuple[list[dict], int]` → `(vacancies, total)`. Each vacancy is normalised to the **hh API shape the rest of the code already expects**: `{"id": str, "name": str, "employer": {"id": str, "name": str}, "has_test": bool, "response_letter_required": bool, "archived": bool}`.
  - `WEB_BASE = "https://hh.ru"`

Field mapping confirmed from the live page (`vacancySearchResult.vacancies[*]`): `vacancyId`, `name`, `company`, `@responseLetterRequired`, `userTestPresent`, `closedForApplicants`, plus `totalResults` on the parent and 50 results per page.

- [ ] **Step 1: Write the failing test**

```python
import pytest

SEARCH_PAGE = (
    '<html>{&#34;vacancySearchResult&#34;:{&#34;totalResults&#34;:2,&#34;vacancies&#34;:['
    '{&#34;vacancyId&#34;:1,&#34;name&#34;:&#34;Python dev&#34;,'
    '&#34;company&#34;:{&#34;id&#34;:9,&#34;name&#34;:&#34;Acme&#34;},'
    '&#34;userTestPresent&#34;:true,&#34;@responseLetterRequired&#34;:false,'
    '&#34;closedForApplicants&#34;:false}]}}</html>'
)


@pytest.mark.asyncio
async def test_search_normalises_web_json_to_the_api_shape(monkeypatch):
    from app.hh import web

    monkeypatch.setattr(web, "_get", _fake_get(SEARCH_PAGE))
    vacancies, total = await web.search_vacancies("u1", {"text": "python"})

    assert total == 2
    assert vacancies[0] == {
        "id": "1",
        "name": "Python dev",
        "employer": {"id": "9", "name": "Acme"},
        "has_test": True,
        "response_letter_required": False,
        "archived": False,
    }


@pytest.mark.asyncio
async def test_search_raises_web_session_expired_on_a_login_wall(monkeypatch):
    from app.hh import web
    from app.services.form_filler import WebSessionExpired

    monkeypatch.setattr(web, "_get", _fake_get("", status=403))
    with pytest.raises(WebSessionExpired):
        await web.search_vacancies("u1", {"text": "python"})
```

`_fake_get` is a small local helper returning an object with `.text`, `.status_code`, `.url` — define it at the top of the test file, do not import a framework for it.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_hh_web.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.hh.web'`

- [ ] **Step 3: Write the implementation**

`_get(session, url, **kw)` is the single choke point: it performs the request, runs `session_looks_dead`, raises `WebSessionExpired`, and enforces the inter-request delay. Everything else in this module goes through it, so the dead-session guard cannot be forgotten in a new function.

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_hh_web.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/hh/web.py backend/tests/test_hh_web.py
git commit -m "feat(hh): vacancy search over the web session"
```

---

### Task 4: Move the vacancy producer and filter preview onto the web search

**Files:**
- Modify: `backend/app/services/vacancy_producer.py` (the hh call inside `produce_jobs`, `backend/app/services/vacancy_producer.py:216`)
- Modify: `backend/app/services/filters_service.py:200` (`preview_filter`)
- Test: `backend/tests/test_vacancy_producer.py`, `backend/tests/test_filters_service.py`

**Interfaces:**
- Consumes: `web.search_vacancies(user_id, params, page) -> (list[dict], int)` from Task 3.
- Produces: no signature change. `produce_jobs(user_id, agent) -> (queued, scanned)` and `preview_filter(user_id, filter_id) -> dict` keep their contracts.

- [ ] **Step 1: Read the current call sites before editing**

Both build hh search params from a `filters` row (`text`, `excluded_text`, `search_field`, `period`, `work_format`, `employment_form`, `area`). The web search takes the **same query-string names** — this is the same search backend, so the param builder is reused as-is, not rewritten. Confirm this against `recon_web_out` before assuming it.

- [ ] **Step 2: Write the failing test**

Extend the existing producer test: assert `produce_jobs` queues jobs when `web.search_vacancies` is mocked to return two vacancies, and that a `has_test` vacancy is still queued (not skipped — the producer must not pre-filter tests; see CLAUDE.md).

- [ ] **Step 3: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_vacancy_producer.py -v`
Expected: FAIL — producer still calls `load_api_client`.

- [ ] **Step 4: Swap the call**

Replace the `load_api_client` + `client.get("vacancies", ...)` pair with `await web.search_vacancies(...)`. Delete the now-orphaned `persist_if_refreshed` bookkeeping **in these two functions only** — it is still needed elsewhere until Task 7.

- [ ] **Step 5: Run the full suite**

Run: `cd backend && python -m pytest tests -q --ignore=tests/e2e`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(hh): produce jobs and preview filters over the web search"
```

---

### Task 5: Apply over the web for vacancies without a test

**Files:**
- Modify: `backend/app/services/form_filler.py` (`_submit`)
- Modify: `backend/app/services/apply.py:201` (`apply_one`)
- Test: `backend/tests/test_apply.py`

**Interfaces:**
- Consumes: `recon_web_out/apply_no_test.json` from Task 1 — the authoritative field list.
- Produces: `form_filler.submit_response(user_id, resume_id, vacancy_id, letter, answers=None) -> tuple[FillStatus, str | None]`. With `answers=None` it posts a plain response (no test fields); with answers it behaves exactly as today's `submit_prepared_form`.

**This is the task that replaces `POST /negotiations`.** `_submit` already posts to `https://hh.ru/applicant/vacancy_response/popup` with `_xsrf`, `vacancy_id`, `resume_hash`, `letter` — the test-only keys are `uidPk`, `guid`, `startTime`, `testRequired`. Task 1 Step 3 establishes whether hh wants them omitted or sent empty.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_plain_response_omits_the_test_only_fields(monkeypatch):
    from app.services import form_filler

    captured = {}
    monkeypatch.setattr(form_filler, "_post_response", lambda **kw: captured.update(kw) or _ok())
    await form_filler.submit_response("u1", "r1", "42", letter="hi", answers=None)

    body = captured["payload"]
    assert body["vacancy_id"] == "42" and body["letter"] == "hi"
    for test_only in ("uidPk", "guid", "startTime", "testRequired"):
        assert test_only not in body
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_apply.py -v`
Expected: FAIL — `submit_response` does not exist.

- [ ] **Step 3: Implement**

Split `_submit` into `_response_payload(...)` (pure, testable) and `_post_response(...)` (the HTTP call). Build the test-only keys only when `answers` is truthy.

- [ ] **Step 4: Rewire `apply_one`**

Replace the `POST /negotiations` call with `submit_response`. **Keep the whole status mapping**: an hh rejection body must still map onto the existing `ApplyStatus` literals. Map an hh 403/login wall onto `token_dead` so the runner's terminal-stop path (`runner._disable_worker`) keeps working — otherwise a dead web session respawns the runner every 15 s forever.

- [ ] **Step 5: Run the full suite**

Run: `cd backend && python -m pytest tests -q --ignore=tests/e2e`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(hh): apply over the web session instead of POST /negotiations"
```

---

### Task 6: Resume list, full resume and negotiation states over the web

**Files:**
- Modify: `backend/app/services/resume_sync.py:73`, `backend/app/services/form_filler.py` (`load_resume`), `backend/app/services/negotiation_sync.py:106`
- Modify: `backend/app/hh/web.py` (add `list_resumes`, `get_resume`, `list_negotiations`)
- Test: `backend/tests/test_resume_sync.py`, `backend/tests/test_negotiation_sync.py`

**Interfaces:**
- Consumes: `recon_web_out/resumes.json`, `recon_web_out/negotiations.json` from Task 1 — field names come from there, not from this document.
- Produces: `web.list_resumes(user_id) -> list[dict]` shaped like the API's `/resumes/mine` items (`id`, `title`, `updated_at`); `web.get_resume(user_id, hh_resume_id) -> dict`; `web.list_negotiations(user_id) -> list[dict]` with `{"vacancy_id", "state", "viewed"}`.

- [ ] **Step 1: Confirm the analytics contract before touching it**

`negotiation_sync.sync_states` writes `hh_state` / `hh_state_at` / `hh_viewed`, and `analytics_summary()` in PG reads them. `hh_state` must keep the exact literals `response` / `invitation` / `discard` — the funnel's "invited" step is `hh_state='invitation'`. If the web page words them differently, map them; do not change the stored values.

- [ ] **Step 2: Write the failing tests**

One per function, asserting the normalised shape above from a captured fixture. Copy the fixture text out of `recon_web_out/*.json`, trimmed to two entries.

- [ ] **Step 3: Run them to verify they fail**

Run: `cd backend && python -m pytest tests/test_resume_sync.py tests/test_negotiation_sync.py -v`
Expected: FAIL

- [ ] **Step 4: Implement and swap the three call sites**

`resume_sync` must keep its orphaned-filter behaviour: a resume that disappears still disables its filters and fires `resume_missing`.

- [ ] **Step 5: Run the full suite**

Run: `cd backend && python -m pytest tests -q --ignore=tests/e2e`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(hh): resumes and negotiation states over the web session"
```

---

### Task 7: Make the OAuth grant optional

**Files:**
- Modify: `backend/app/services/hh_auth.py` (`_run_oauth`, `_run_oauth_email_code`)
- Modify: `backend/app/api/auth.py` (connect status)
- Test: `backend/tests/test_hh_auth.py`

**Interfaces:**
- Consumes: `authorize.get_auth_code` / `get_auth_code_via_email_code`, unchanged.
- Produces: a connect job that succeeds on cookies alone.

Today a `geo_forbidden` at the grant step throws away a **perfectly good web session** — the login worked, we just never save the cookies because `_extract_code` raised first. After Tasks 3–6 the cookies are all the product needs.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_connect_succeeds_on_cookies_when_hh_refuses_the_oauth_code(monkeypatch):
    """geo_forbidden must not discard a working web session."""
    # get_auth_code raises RuntimeError("...geo_forbidden..."), cookies were captured.
    # Expect: job status "success", hh_credentials row written with
    # web_cookies_encrypted set and access_token_encrypted NULL.
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_hh_auth.py -v`
Expected: FAIL — the job finishes `failed`.

- [ ] **Step 3: Change `authorize.py` to return cookies alongside the failure**

Return `(code | None, cookies)` and let the caller decide, instead of raising before the cookies are read. Persist with a NULL access token when the grant failed.

- [ ] **Step 4: Make the DB and the status endpoint agree**

`hh_credentials.access_token_encrypted` must become nullable (new migration), and `get_credentials_status` must report `connected: True` for a cookies-only row. `token_refresh.refresh_due` must skip rows with no refresh token instead of erroring.

- [ ] **Step 5: Run the full suite**

Run: `cd backend && python -m pytest tests -q --ignore=tests/e2e`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(hh): connect on the web session alone when hh refuses the OAuth grant"
```

---

## Self-Review Notes

- **Known gap, deliberate:** `extension_resume.py` (resume PDF for the browser extension) still uses `load_api_client`. It is not on the apply path and the extension degrades gracefully without it. Migrate it in a follow-up once Task 6 proves the resume endpoints.
- **Known risk:** Task 5 Step 3 is the only place where a wrong guess silently sends a broken response to a real employer. Its test asserts payload shape, but the first live run must be done on **one** vacancy with the worker in manual mode, and the result checked on hh.ru by hand before enabling the loop.
- **Blocked-by:** Tasks 3–6 all depend on Task 1's captures. If Task 1 Step 4 finds the web path is *also* geo-blocked, the entire plan is void and the proxy option is the only remaining path.
