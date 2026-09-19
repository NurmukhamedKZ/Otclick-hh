from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _chain(data=None):
    q = MagicMock()
    q.select.return_value = q
    q.update.return_value = q
    q.insert.return_value = q
    q.upsert.return_value = q
    q.eq.return_value = q
    q.in_.return_value = q
    q.maybe_single.return_value = q
    q.execute.return_value = SimpleNamespace(data=data)
    return q


def test_transition_is_conditional_on_current_status():
    from app.services import vacancy_pipeline as vp

    q = _chain(data=[{"id": "p1", "status": "selected"}])
    sb = MagicMock()
    sb.table.return_value = q

    with patch.object(vp, "service_client", sb):
        changed = vp.transition(
            user_id="u1",
            pipeline_id="p1",
            from_statuses=["review", "scored"],
            to_status="selected",
        )

    assert changed is True
    q.in_.assert_called_once_with("status", ["review", "scored"])
    payload = q.update.call_args.args[0]
    assert payload["status"] == "selected"


def test_persist_existing_vacancy_does_not_reset_lifecycle():
    from app.services import vacancy_pipeline as vp

    existing = _chain(data={"id": "p1", "status": "selected", "resume_id": "r1"})
    update = _chain(data=[{"id": "p1", "status": "selected"}])
    sb = MagicMock()

    calls = 0

    def table(name):
        nonlocal calls
        assert name == "vacancy_pipeline"
        calls += 1
        return existing if calls == 1 else update

    sb.table.side_effect = table
    vacancy = {
        "id": "123",
        "name": "CIO",
        "employer": {"id": "42", "name": "Acme"},
        "area": {"name": "Москва"},
    }

    with patch.object(vp, "service_client", sb):
        row = vp.persist_discovered(
            user_id="u1", resume_id="r1", vacancy=vacancy, source_id=None
        )

    assert row["status"] == "selected"
    payload = update.update.call_args.args[0]
    assert "status" not in payload
    assert payload["title"] == "CIO"
