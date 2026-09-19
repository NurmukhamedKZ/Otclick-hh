from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _query_mock():
    q = MagicMock()
    for name in ("select", "eq", "neq", "is_", "in_", "order", "limit", "update", "insert", "delete", "upsert", "maybe_single"):
        getattr(q, name).return_value = q
    q.execute.return_value = SimpleNamespace(data=[{"ok": True}])
    return q


def test_progress_counts_terminal_and_current_job():
    from app.services import send_runtime_control as svc

    batch = {"id": "b1", "status": "running", "total_jobs": 5}
    jobs = [
        {"id": "q1", "status": "sent"},
        {"id": "q2", "status": "failed"},
        {"id": "q3", "status": "manual_required"},
        {"id": "q4", "status": "queued"},
        {"id": "q5", "status": "sending", "hh_vacancy_id": "123"},
    ]
    progress = svc._progress(batch, jobs)

    assert progress["total"] == 5
    assert progress["processed"] == 3
    assert progress["queued"] == 1
    assert progress["sending"] == 1
    assert progress["current"]["id"] == "q5"


def test_lease_active_requires_unexpired_timestamp():
    from app.services import send_runtime_control as svc

    future = datetime.now(UTC) + timedelta(minutes=1)
    past = datetime.now(UTC) - timedelta(minutes=1)
    assert svc._lease_is_active({"lease_owner": "w1", "lease_expires_at": future.isoformat()}) is True
    assert svc._lease_is_active({"lease_owner": "w1", "lease_expires_at": past.isoformat()}) is False
    assert svc._lease_is_active({"lease_owner": None, "lease_expires_at": future.isoformat()}) is False


def test_resume_creates_snapshot_batch_and_sets_running():
    from app.services import send_runtime_control as svc

    q = _query_mock()
    with (
        patch.object(svc, "_ensure_control", return_value={"active_batch_id": None}),
        patch.object(svc, "_create_batch", return_value="b1") as create_batch,
        patch.object(svc, "_state", return_value={"desired_state": "running"}),
        patch.object(svc.service_client, "table", return_value=q),
    ):
        state = svc._set_control("u1", action="resume", safety_interval_seconds=15)

    assert state["desired_state"] == "running"
    create_batch.assert_called_once_with("u1")
    payloads = [call.args[0] for call in q.update.call_args_list if call.args]
    assert any(p.get("desired_state") == "running" and p.get("active_batch_id") == "b1" for p in payloads)
    assert any(p.get("safety_interval_seconds") == 15 for p in payloads)


def test_pause_keeps_active_batch_but_marks_control_paused():
    from app.services import send_runtime_control as svc

    q = _query_mock()
    with (
        patch.object(svc, "_ensure_control", return_value={"active_batch_id": "b1"}),
        patch.object(svc, "_state", return_value={"desired_state": "paused"}),
        patch.object(svc.service_client, "table", return_value=q),
    ):
        state = svc._set_control("u1", action="pause", safety_interval_seconds=None)

    assert state["desired_state"] == "paused"
    payloads = [call.args[0] for call in q.update.call_args_list if call.args]
    assert any(p.get("status") == "paused" for p in payloads)
    assert any(p.get("desired_state") == "paused" and "active_batch_id" not in p for p in payloads)


def test_stop_after_current_waits_only_when_job_is_sending():
    from app.services import send_runtime_control as svc

    q = _query_mock()
    with (
        patch.object(svc, "_ensure_control", return_value={"active_batch_id": "b1"}),
        patch.object(svc, "_batch_jobs", return_value=[{"id": "q1", "status": "sending"}]),
        patch.object(svc, "_state", return_value={"desired_state": "stop_after_current"}),
        patch.object(svc.service_client, "table", return_value=q),
    ):
        state = svc._set_control("u1", action="stop_after_current", safety_interval_seconds=None)

    assert state["desired_state"] == "stop_after_current"
    payloads = [call.args[0] for call in q.update.call_args_list if call.args]
    assert any(p.get("desired_state") == "stop_after_current" for p in payloads)


def test_stop_after_current_without_inflight_job_pauses_immediately():
    from app.services import send_runtime_control as svc

    q = _query_mock()
    with (
        patch.object(svc, "_ensure_control", return_value={"active_batch_id": "b1"}),
        patch.object(svc, "_batch_jobs", return_value=[{"id": "q1", "status": "queued"}]),
        patch.object(svc, "_state", return_value={"desired_state": "paused"}),
        patch.object(svc.service_client, "table", return_value=q),
    ):
        state = svc._set_control("u1", action="stop_after_current", safety_interval_seconds=None)

    assert state["desired_state"] == "paused"
    payloads = [call.args[0] for call in q.update.call_args_list if call.args]
    assert any(p.get("desired_state") == "paused" for p in payloads)
    assert any(p.get("status") == "paused" for p in payloads)


def test_acquire_lease_returns_only_current_active_batch():
    from app.services import send_runtime_control as svc

    with (
        patch.object(svc, "_rpc_bool", return_value=True) as rpc,
        patch.object(svc, "_ensure_control", return_value={"active_batch_id": "b1"}),
    ):
        batch_id = svc.acquire_lease("u1", "worker-1", 300)

    assert batch_id == "b1"
    rpc.assert_called_once_with(
        "acquire_application_send_lease",
        {"p_user_id": "u1", "p_owner": "worker-1", "p_ttl_seconds": 300},
    )
