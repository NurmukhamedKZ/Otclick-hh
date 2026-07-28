"""Regressions for the AUDIT.md «Мелочи и полировка» round."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# --- 429 from hh is transient, not a failed apply ---------------------------

def _resp(status: int) -> MagicMock:
    return MagicMock(status_code=status)


def test_429_maps_to_too_many_requests():
    from app.hh import errors

    with pytest.raises(errors.TooManyRequests):
        errors.ApiError.raise_for_status(_resp(429), {})


def test_429_is_not_a_client_error():
    """Иначе его глотает `except ClientError` в apply_one и пишет status=failed."""
    from app.hh import errors

    assert not issubclass(errors.TooManyRequests, errors.ClientError)


def test_runner_treats_429_as_transient_with_backoff():
    from app.hh import errors
    from app.worker import runner

    ex = errors.TooManyRequests(_resp(429), {})
    assert runner._is_transient(ex) is True
    assert runner._retry_delay(ex) == runner.RETRY_THROTTLED_SLEEP_S
    assert runner._retry_delay(RuntimeError()) < runner.RETRY_THROTTLED_SLEEP_S


# --- terminal stop clears the persisted flag --------------------------------

@pytest.mark.asyncio
async def test_disable_worker_clears_flag():
    """worker_main перезапускал бы раннер каждые 15 с и спамил уведомлениями."""
    from app.worker import runner

    with patch.object(
        runner.worker_control, "set_enabled", AsyncMock()
    ) as set_enabled:
        await runner._disable_worker("u1")
    set_enabled.assert_awaited_once_with("u1", False)


# --- /api/worker/status is honest about "не поднялся ещё" -------------------

async def _status(runtime_row: dict | None) -> object:
    from app.api import worker as worker_api

    with (
        patch.object(worker_api.worker_control, "is_enabled", AsyncMock(return_value=True)),
        patch.object(
            worker_api.worker_control, "is_agent_enabled", AsyncMock(return_value=False)
        ),
        patch("app.services.worker_runtime.get", AsyncMock(return_value=runtime_row)),
        patch(
            "app.services.plan.get_limits",
            AsyncMock(return_value={"mode": "auto", "daily": 100, "total": None}),
        ),
        patch("app.worker.limiter.sent_total", return_value=12),
        patch("app.worker.limiter._read_day_count", return_value=3),
        patch("app.worker.limiter._tz_for_user", return_value=SimpleNamespace()),
        patch("app.worker.limiter._today_local", return_value="2026-07-27"),
    ):
        return await worker_api.worker_status(user_id="u1")


@pytest.mark.asyncio
async def test_status_starting_when_no_heartbeat_yet():
    assert (await _status(None)).state == "starting"


@pytest.mark.asyncio
async def test_status_starting_on_stale_stopped_row():
    assert (await _status({"state": "stopped"})).state == "starting"


@pytest.mark.asyncio
async def test_status_running_when_runner_says_so():
    assert (await _status({"state": "running", "queued": 4})).state == "running"


# --- captcha dismiss only закрывает окно ------------------------------------

@pytest.mark.asyncio
async def test_dismiss_does_not_stop_the_worker():
    from app.api import captcha as captcha_api

    assert "worker_control" not in dir(captcha_api)
    with patch.object(
        captcha_api.captcha_service, "mark_solved", AsyncMock()
    ) as solved:
        out = await captcha_api.dismiss("req-1", user_id="u1")
    solved.assert_awaited_once_with("u1")
    assert out.dismissed is True
