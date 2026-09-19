import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")


async def test_retry_once_on_transient_then_success():
    import requests as req

    from app.worker import runner
    from app.worker.queue import ApplyJob

    calls = []

    async def fake_apply_one(user_id, resume_id, vacancy_id, agent, filter_id=None):
        calls.append(vacancy_id)
        if len(calls) == 1:
            raise req.ConnectionError("boom")
        return "sent"

    with patch.object(runner.apply_service, "apply_one", side_effect=fake_apply_one):
        job = ApplyJob(user_id="u1", resume_id="r1", vacancy_id="v1", filter_id=None)
        status = await runner._maybe_apply_with_retry(job, MagicMock())

    assert status == "sent"
    assert len(calls) == 2


async def test_no_retry_on_fatal():
    from app.hh import errors as hh_errors
    from app.worker import runner
    from app.worker.queue import ApplyJob

    calls = []

    async def fake_apply_one(user_id, resume_id, vacancy_id, agent, filter_id=None):
        calls.append(vacancy_id)
        resp = type("R", (), {"status_code": 400, "request": None, "headers": {}})()
        raise hh_errors.BadRequest(resp, {"description": "nope"})

    with patch.object(runner.apply_service, "apply_one", side_effect=fake_apply_one):
        job = ApplyJob(user_id="u1", resume_id="r1", vacancy_id="v1", filter_id=None)
        status = await runner._maybe_apply_with_retry(job, MagicMock())

    assert status == "failed"
    assert len(calls) == 1


async def test_retry_once_then_give_up():
    import requests as req

    from app.worker import runner
    from app.worker.queue import ApplyJob

    calls = []

    async def fake_apply_one(user_id, resume_id, vacancy_id, agent, filter_id=None):
        calls.append(vacancy_id)
        raise req.Timeout("slow")

    with patch.object(runner.apply_service, "apply_one", side_effect=fake_apply_one):
        job = ApplyJob(user_id="u1", resume_id="r1", vacancy_id="v1", filter_id=None)
        status = await runner._maybe_apply_with_retry(job, MagicMock())

    assert status == "failed"
    assert len(calls) == 2


async def test_is_transient_classification():
    import requests as req

    from app.hh import errors as hh_errors
    from app.worker import runner

    resp = type("R", (), {"status_code": 500, "request": None, "headers": {}})()
    assert runner._is_transient(hh_errors.InternalServerError(resp, {})) is True
    assert runner._is_transient(hh_errors.BadGateway(resp, {})) is True
    assert runner._is_transient(req.ConnectionError("x")) is True
    assert runner._is_transient(req.Timeout("x")) is True

    resp4 = type("R", (), {"status_code": 400, "request": None, "headers": {}})()
    assert runner._is_transient(hh_errors.BadRequest(resp4, {"description": "x"})) is False
    assert runner._is_transient(ValueError("nope")) is False


async def test_registry_start_stop_lifecycle():
    from app.worker import runner

    runner.reset_registry()
    registry = runner.get_registry()

    # Patch _run_loop to a no-op coroutine that waits to be cancelled.
    import asyncio

    async def idle_loop(handle):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise

    with patch.object(runner, "_run_loop", side_effect=idle_loop):
        handle = await registry.start("u1")
        assert handle.task is not None
        assert handle.state == "running"
        # Idempotent: second start returns the same handle.
        again = await registry.start("u1")
        assert again is handle

        stopped = await registry.stop("u1")
        assert stopped is True
        assert registry.get("u1") is None


async def test_registry_reconcile_independent_loops():
    import asyncio

    from app.worker import runner

    runner.reset_registry()
    registry = runner.get_registry()

    async def idle_loop(handle):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise

    with (
        patch.object(runner, "_run_loop", side_effect=idle_loop),
        patch.object(runner, "_recruiter_loop", side_effect=idle_loop),
    ):
        # agent only — no apply task
        h = await registry.reconcile("u1", False, True)
        assert h.task is None
        assert h.recruiter_task is not None and not h.recruiter_task.done()

        # add apply, keep agent — same handle
        h2 = await registry.reconcile("u1", True, True)
        assert h2 is h
        assert h.task is not None and not h.task.done()
        assert h.recruiter_task is not None and not h.recruiter_task.done()
        assert registry.active_user_ids() == ["u1"]

        # drop apply, keep agent
        await registry.reconcile("u1", False, True)
        assert h.task is None
        assert h.recruiter_task is not None and not h.recruiter_task.done()

        # drop everything → handle gone
        await registry.reconcile("u1", False, False)
        assert registry.get("u1") is None
        assert registry.active_user_ids() == []


async def _drain_loop(handle, *, limits, check_result="allowed", produce=(0, 0)):
    """Прогнать _run_loop с замоканными зависимостями до самоостановки."""
    import asyncio
    from unittest.mock import AsyncMock

    from app.worker import runner

    produce_calls = []

    async def fake_produce(user_id, agent):
        produce_calls.append(user_id)
        return produce

    with (
        patch.object(runner.plan_service, "get_limits", new=AsyncMock(return_value=limits)),
        patch.object(runner.limiter, "check", new=AsyncMock(return_value=check_result)),
        patch("app.services.vacancy_producer.produce_jobs", new=fake_produce),
        patch.object(runner, "heartbeat", new=AsyncMock()),
        patch.object(runner, "notify", new=AsyncMock()) as notify_mock,
        patch.object(runner.worker_control, "set_enabled", new=AsyncMock()) as set_enabled,
    ):
        await asyncio.wait_for(runner._run_loop(handle), timeout=5)
    return produce_calls, notify_mock, set_enabled


async def test_manual_mode_runs_one_batch_then_stops():
    from app.worker import runner
    from app.worker.queue import drop_user_queue

    drop_user_queue("u-manual")
    handle = runner.RunnerHandle(user_id="u-manual")
    produce_calls, _, set_enabled = await _drain_loop(
        handle, limits={"mode": "manual", "daily": None, "total": 30}
    )

    # Ровно один заход продюсера, затем самоостановка — не бесконечная петля.
    assert produce_calls == ["u-manual"]
    assert handle.state == "idle"
    set_enabled.assert_awaited_once_with("u-manual", False)


async def test_limit_total_stops_runner_and_clears_flag():
    from app.worker import runner
    from app.worker.queue import drop_user_queue

    drop_user_queue("u-capped")
    handle = runner.RunnerHandle(user_id="u-capped")
    produce_calls, notify_mock, set_enabled = await _drain_loop(
        handle,
        limits={"mode": "manual", "daily": None, "total": 30},
        check_result="limit_total",
    )

    assert produce_calls == []  # до продюсера не дошли
    assert handle.state == "stopped"
    # Флаг гасим, иначе worker_main поднимает раннер каждые 15с по кругу.
    set_enabled.assert_awaited_once_with("u-capped", False)
    assert notify_mock.await_args[0][1] == "limit_total"


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

    def _fake_persist(user_id, cookies):
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
