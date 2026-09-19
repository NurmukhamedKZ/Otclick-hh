import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")


def _insert_mock(returned_row):
    chain = MagicMock()
    chain.insert.return_value = chain
    chain.update.return_value = chain
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.order.return_value = chain
    chain.execute.return_value = SimpleNamespace(data=[returned_row] if returned_row else [])
    return chain


async def test_create_request_uploads_image_and_inserts_row():
    from app.services import captcha as captcha_mod

    table_chain = _insert_mock({"id": "c1", "storage_path": "u1/abc.png"})
    storage_bucket = MagicMock()
    sb = MagicMock()
    sb.table.return_value = table_chain
    sb.storage.from_.return_value = storage_bucket

    resp = MagicMock()
    resp.content = b"PNGDATA"
    resp.raise_for_status.return_value = None

    with (
        patch.object(captcha_mod, "service_client", sb),
        patch.object(captcha_mod.requests, "get", return_value=resp),
    ):
        row = await captcha_mod.create_request("u1", "https://hh.ru/captcha.png")

    storage_bucket.upload.assert_called_once()
    insert_arg = table_chain.insert.call_args[0][0]
    assert insert_arg["user_id"] == "u1"
    assert insert_arg["captcha_url"] == "https://hh.ru/captcha.png"
    assert insert_arg["storage_path"] is not None
    assert insert_arg["solved"] is False
    assert row["id"] == "c1"


async def test_create_request_image_fetch_fails_storage_path_none():
    from app.services import captcha as captcha_mod

    table_chain = _insert_mock({"id": "c2", "storage_path": None})
    storage_bucket = MagicMock()
    sb = MagicMock()
    sb.table.return_value = table_chain
    sb.storage.from_.return_value = storage_bucket

    with (
        patch.object(captcha_mod, "service_client", sb),
        patch.object(captcha_mod.requests, "get", side_effect=Exception("boom")),
    ):
        await captcha_mod.create_request("u1", "https://hh.ru/captcha.png")

    storage_bucket.upload.assert_not_called()
    insert_arg = table_chain.insert.call_args[0][0]
    assert insert_arg["storage_path"] is None


async def test_mark_solved_updates_unsolved_rows():
    from app.services import captcha as captcha_mod

    chain = _insert_mock(None)
    sb = MagicMock()
    sb.table.return_value = chain

    with patch.object(captcha_mod, "service_client", sb):
        await captcha_mod.mark_solved("u1")

    update_arg = chain.update.call_args[0][0]
    assert update_arg["solved"] is True
    assert "solved_at" in update_arg
    # scoped to user + unsolved
    eq_calls = [c.args for c in chain.eq.call_args_list]
    assert ("user_id", "u1") in eq_calls
    assert ("solved", False) in eq_calls


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
