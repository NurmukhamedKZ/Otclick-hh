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


async def test_registry_resume_captcha():
    from app.worker import runner

    runner.reset_registry()
    registry = runner.get_registry()

    import asyncio

    async def idle_loop(handle):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise

    with patch.object(runner, "_run_loop", side_effect=idle_loop):
        handle = await registry.start("u2")
        handle.state = "paused_captcha"
        assert registry.resume_captcha("u2") is True
        assert handle.captcha_event.is_set()
        # Wrong state returns False.
        handle.state = "running"
        assert registry.resume_captcha("u2") is False
        await registry.stop("u2")


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


async def test_probe_me_ok():
    from unittest.mock import MagicMock

    from app.worker import runner

    client = MagicMock()
    client.access_token = "tok"
    client.get.return_value = {"id": "me1"}

    with (
        patch.object(runner, "load_api_client", return_value=client),
        patch.object(runner, "persist_if_refreshed"),
    ):
        result = await runner._probe_me("u1")
    assert result == "ok"


async def test_probe_me_captcha():
    from unittest.mock import MagicMock

    from app.hh import errors as hh_errors
    from app.worker import runner

    client = MagicMock()
    client.access_token = "tok"
    resp = type("R", (), {"status_code": 403, "request": None, "headers": {}})()
    data = {"errors": [{"value": "captcha_required", "captcha_url": "https://x"}]}
    client.get.side_effect = hh_errors.CaptchaRequired(resp, data)

    with (
        patch.object(runner, "load_api_client", return_value=client),
        patch.object(runner, "persist_if_refreshed"),
    ):
        result = await runner._probe_me("u1")
    assert result == "captcha"


async def test_probe_me_forbidden_token_dead():
    from unittest.mock import AsyncMock, MagicMock

    from app.hh import errors as hh_errors
    from app.worker import runner

    client = MagicMock()
    client.access_token = "tok"
    resp = type("R", (), {"status_code": 403, "request": None, "headers": {}})()
    client.get.side_effect = hh_errors.Forbidden(resp, {"description": "nope"})

    with (
        patch.object(runner, "load_api_client", return_value=client),
        patch.object(runner, "persist_if_refreshed"),
        patch.object(runner, "mark_invalid", new=AsyncMock()) as mi,
    ):
        result = await runner._probe_me("u1")
    assert result == "token_dead"
    mi.assert_awaited_once()


async def test_probe_me_load_fails_token_dead():
    from app.worker import runner

    def _boom(_uid):
        raise RuntimeError("no creds")

    with patch.object(runner, "load_api_client", side_effect=_boom):
        result = await runner._probe_me("u1")
    assert result == "token_dead"


async def test_probe_me_forbidden_banned():
    from unittest.mock import AsyncMock, MagicMock

    from app.hh import errors as hh_errors
    from app.worker import runner

    client = MagicMock()
    client.access_token = "tok"
    resp = type("R", (), {"status_code": 403, "request": None, "headers": {}})()
    client.get.side_effect = hh_errors.Forbidden(
        resp, {"errors": [{"type": "auth", "value": "account_blocked"}]}
    )

    with (
        patch.object(runner, "load_api_client", return_value=client),
        patch.object(runner, "persist_if_refreshed"),
        patch.object(runner, "mark_invalid", new=AsyncMock()) as mi,
    ):
        result = await runner._probe_me("u1")
    assert result == "banned"
    mi.assert_awaited_once()
