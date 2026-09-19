from unittest.mock import AsyncMock, patch


async def test_real_apply_is_blocked_before_any_hh_session_access():
    from app.services import form_filler

    load_session = AsyncMock()
    with (
        patch.object(form_filler.settings, "ALLOW_REAL_APPLY", False),
        patch.object(form_filler, "load_web_session", load_session),
    ):
        status, error = await form_filler.submit_response(
            user_id="u1",
            resume_id="r1",
            vacancy_id="v1",
            letter="approved-looking text",
        )

    assert status == "failed"
    assert error == "real_apply_disabled"
    load_session.assert_not_awaited()


async def test_prepared_form_uses_the_same_real_apply_gate():
    from app.services import form_filler

    load_session = AsyncMock()
    with (
        patch.object(form_filler.settings, "ALLOW_REAL_APPLY", False),
        patch.object(form_filler, "load_web_session", load_session),
    ):
        status, error = await form_filler.submit_prepared_form(
            user_id="u1",
            resume_id="r1",
            vacancy_id="v1",
            answers=[{"task_id": "1", "type": "text", "answer": "x"}],
            letter="text",
        )

    assert status == "failed"
    assert error == "real_apply_disabled"
    load_session.assert_not_awaited()


async def test_env_gate_alone_does_not_submit_without_the_user_switch():
    """Two keys: ALLOW_REAL_APPLY is the deployment gate, the per-user switch is
    the other half. Either one off means nothing reaches hh."""
    from app.services import form_filler, worker_control

    load_session = AsyncMock()
    flags = AsyncMock(return_value={"real_apply": False})
    with (
        patch.object(form_filler.settings, "ALLOW_REAL_APPLY", True),
        patch.object(worker_control, "get_flags", flags),
        patch.object(form_filler, "load_web_session", load_session),
    ):
        status, error = await form_filler.submit_response(
            user_id="u1",
            resume_id="r1",
            vacancy_id="v1",
            letter="approved-looking text",
        )

    assert status == "failed"
    assert error == "real_apply_disabled_by_user"
    load_session.assert_not_awaited()
