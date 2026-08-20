"""Regressions for AUDIT.md items 13-21 (18 intentionally out of scope)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _chain(final_data):
    c = MagicMock()
    for m in ("select", "eq", "in_", "is_", "update", "upsert", "delete", "not_", "limit", "order"):
        getattr(c, m).return_value = c
    c.not_.in_.return_value = c
    c.execute.return_value = SimpleNamespace(data=final_data)
    return c


# --- 13: producer and apply agree on what counts as "already spent" ---------

def test_producer_keeps_retryable_rows_eligible():
    from app.services import vacancy_producer as vp

    rows = [
        {"vacancy_id": "1", "status": "sent"},
        {"vacancy_id": "2", "status": "form_required"},  # never reached hh
        {"vacancy_id": "3", "status": "form_pending"},   # awaiting user approval
        {"vacancy_id": "4", "status": "failed"},
    ]
    with patch.object(vp, "service_client") as sc:
        sc.table.return_value = _chain(rows)
        spent = vp._existing_vacancy_ids("u1", ["1", "2", "3", "4"])
    assert spent == {"1", "3", "4"}


def test_apply_and_producer_share_one_retryable_set():
    """The two used to disagree: apply let form_required through, the producer
    filtered it out first, so those vacancies were unreachable forever."""
    from app.services import apply as apply_service
    from app.services import vacancy_producer as vp

    assert vp.RETRYABLE_STATUSES is apply_service.RETRYABLE_STATUSES
    assert "form_required" in apply_service.RETRYABLE_STATUSES
    assert "form_pending" not in apply_service.RETRYABLE_STATUSES


@pytest.mark.parametrize(
    "status,expected",
    [("sent", True), ("form_required", False), ("form_pending", True), ("failed", True)],
)
def test_already_applied_matches_the_shared_set(status, expected):
    from app.services import apply as apply_service

    with patch.object(apply_service, "service_client") as sc:
        sc.table.return_value = _chain([{"id": "x", "status": status}])
        assert apply_service._already_applied("u1", "v1") is expected


# --- 15: a deleted resume must not leave a silently dead worker -------------

def test_disable_orphaned_filters_targets_enabled_null_resume_rows():
    from app.services import resume_sync

    chain = _chain([{"id": "f1"}, {"id": "f2"}])
    with patch.object(resume_sync, "service_client") as sc:
        sc.table.return_value = chain
        disabled = resume_sync._disable_orphaned_filters("u1")

    assert disabled == ["f1", "f2"]
    chain.update.assert_called_once_with({"enabled": False})
    chain.is_.assert_called_once_with("resume_id", "null")


@pytest.mark.asyncio
async def test_sync_resumes_notifies_when_filters_were_orphaned():
    from app.services import resume_sync

    client = MagicMock(access_token="t")
    client.get.return_value = {"items": []}
    with patch.object(resume_sync.web, "list_resumes", new=AsyncMock(return_value=[])), \
         patch.object(resume_sync, "_upsert_resumes", return_value=[]), \
         patch.object(resume_sync, "_disable_orphaned_filters", return_value=["f1"]), \
         patch.object(resume_sync, "notify", new=AsyncMock()) as notify:
        await resume_sync.sync_resumes("u1")

    assert notify.await_count == 1
    assert notify.await_args[0][1] == "resume_missing"
    assert notify.await_args[0][2]["disabled_filters"] == 1


@pytest.mark.asyncio
async def test_sync_resumes_stays_quiet_when_nothing_was_orphaned():
    from app.services import resume_sync

    client = MagicMock(access_token="t")
    client.get.return_value = {"items": []}
    with patch.object(resume_sync.web, "list_resumes", new=AsyncMock(return_value=[])), \
         patch.object(resume_sync, "_upsert_resumes", return_value=[]), \
         patch.object(resume_sync, "_disable_orphaned_filters", return_value=[]), \
         patch.object(resume_sync, "notify", new=AsyncMock()) as notify:
        await resume_sync.sync_resumes("u1")
    assert notify.await_count == 0


# --- 17: long sleeps publish their state before sleeping -------------------

@pytest.mark.asyncio
async def test_cluster_break_publishes_heartbeat_before_sleeping():
    """The break lasts 1-2h; without a pre-sleep heartbeat the UI reported
    "работает" for the whole window."""
    import asyncio

    from app.worker import runner
    from app.worker.queue import ApplyJob, drop_user_queue, get_user_queue

    drop_user_queue("u1")
    queue = get_user_queue("u1")
    await queue.put(ApplyJob(user_id="u1", resume_id="r1", vacancy_id="v1"))

    order: list[str] = []
    handle = runner.RunnerHandle(user_id="u1", agent=MagicMock())
    handle.cluster = MagicMock()
    handle.cluster.should_break.return_value = True
    handle.cluster.next_break_seconds.return_value = 3600.0

    async def _sleep(_s):
        order.append("sleep")
        raise asyncio.CancelledError  # stop the loop right after the break

    async def _hb(*a, **kw):
        order.append("heartbeat")

    with patch.object(runner, "heartbeat", new=_hb), \
         patch.object(runner.limiter, "check", new=AsyncMock(return_value="allowed")), \
         patch.object(
             runner.plan_service,
             "get_limits",
             new=AsyncMock(return_value={"mode": "auto", "daily": 100, "total": None}),
         ), \
         patch.object(runner.asyncio, "sleep", new=_sleep), \
         patch("app.services.vacancy_producer.produce_jobs", new=AsyncMock(return_value=(1, 0))):
        with pytest.raises(asyncio.CancelledError):
            await runner._run_loop(handle)

    assert "sleep" in order
    assert order.index("heartbeat") < order.index("sleep")
    drop_user_queue("u1")


# --- 20: internal cron secret compared in constant time --------------------

def test_internal_token_uses_constant_time_compare():
    import hmac

    from app.api import internal

    with patch.object(internal.settings, "INTERNAL_CRON_TOKEN", "s3cret"), \
         patch.object(hmac, "compare_digest", wraps=hmac.compare_digest) as cmp:
        internal._require_internal_token("s3cret")
    assert cmp.called


def test_internal_token_rejects_wrong_and_empty_values():
    from fastapi import HTTPException

    from app.api import internal

    with patch.object(internal.settings, "INTERNAL_CRON_TOKEN", "s3cret"):
        for bad in (None, "", "nope", "s3cre"):
            with pytest.raises(HTTPException) as ex:
                internal._require_internal_token(bad)
            assert ex.value.status_code == 403


def test_internal_endpoints_closed_when_no_token_configured():
    from fastapi import HTTPException

    from app.api import internal

    with patch.object(internal.settings, "INTERNAL_CRON_TOKEN", ""):
        with pytest.raises(HTTPException):
            internal._require_internal_token("")


# --- 21: notifications are actually pruned ---------------------------------

@pytest.mark.asyncio
async def test_prune_notifications_calls_the_rpc_with_retention_windows():
    from app.services import retention

    with patch.object(retention, "service_client") as sc:
        sc.rpc.return_value.execute.return_value = SimpleNamespace(data=42)
        out = await retention.prune_notifications()

    assert out == {"status": "ok", "removed": 42}
    fn, args = sc.rpc.call_args[0]
    assert fn == "prune_notifications"
    assert args == {
        "p_read_days": retention.READ_RETENTION_DAYS,
        "p_keep_days": retention.MAX_RETENTION_DAYS,
    }


@pytest.mark.asyncio
async def test_prune_notifications_never_raises():
    from app.services import retention

    with patch.object(retention, "service_client") as sc:
        sc.rpc.side_effect = RuntimeError("pg down")
        out = await retention.prune_notifications()
    assert out == {"status": "error", "removed": 0}
