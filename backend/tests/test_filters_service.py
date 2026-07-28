import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service")
os.environ.setdefault("FERNET_KEY", "kPpDeJjFqDppkMm6QHzqFkkSgFwsKtGzh4WeZ5dKZHc=")


def _fluent(final_data):
    """Build chainable mock returning .execute() → SimpleNamespace(data=final_data)."""
    chain = MagicMock()
    chain.select.return_value = chain
    chain.insert.return_value = chain
    chain.update.return_value = chain
    chain.delete.return_value = chain
    chain.eq.return_value = chain
    chain.order.return_value = chain
    chain.maybe_single.return_value = chain
    chain.not_ = chain
    chain.is_.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = SimpleNamespace(data=final_data)
    return chain


def test_filter_to_search_params_full():
    from app.services.filters_service import PREVIEW_PER_PAGE, _filter_to_search_params

    params = _filter_to_search_params({
        "text": "python backend",
        "area": 40,
        "excluded_text": "продажи, стажёр",
        "experience": "between1And3",
        "work_format": "REMOTE",
        "employment_form": "FULL",
        "search_field": "name",
        "period": 7,
    })
    assert params["text"] == "python backend"
    assert params["area"] == 40
    assert params["excluded_text"] == "продажи, стажёр"
    assert params["experience"] == "between1And3"
    assert params["work_format"] == "REMOTE"
    assert params["employment_form"] == "FULL"
    assert params["search_field"] == "name"
    assert params["period"] == 7
    assert params["per_page"] == PREVIEW_PER_PAGE


def test_filter_to_search_params_skips_none():
    from app.services.filters_service import _filter_to_search_params

    params = _filter_to_search_params({"text": None, "area": None, "excluded_text": None})
    assert "text" not in params
    assert "area" not in params
    assert "excluded_text" not in params


async def test_create_filter_no_resume_id():
    from app.services import filters_service

    table = _fluent([{
        "id": "f1", "resume_id": None, "text": "py", "area": 40,
        "experience": None, "work_format": None, "employment_form": None,
        "search_field": None, "period": None,
        "excluded_text": None, "enabled": True,
        "created_at": None,
    }])
    with patch.object(filters_service, "service_client") as sc:
        sc.table.return_value = table
        row = await filters_service.create_filter("u1", {"text": "py", "area": 40})
    assert row["id"] == "f1"
    table.insert.assert_called_once()
    inserted = table.insert.call_args[0][0]
    assert inserted["user_id"] == "u1"
    assert inserted["text"] == "py"


async def test_has_active_filter_true():
    from app.services import filters_service

    table = _fluent([{"id": "f1"}])
    with patch.object(filters_service, "service_client") as sc:
        sc.table.return_value = table
        assert await filters_service.has_active_filter("u1") is True


async def test_has_active_filter_false():
    from app.services import filters_service

    table = _fluent([])
    with patch.object(filters_service, "service_client") as sc:
        sc.table.return_value = table
        assert await filters_service.has_active_filter("u1") is False


async def test_create_filter_seeds_from_resume():
    from app.services import filters_service

    resume_chain = _fluent({
        "id": "r1", "title": "Frontend developer",
    })
    insert_chain = _fluent([{"id": "f1", "resume_id": "r1"}])
    with patch.object(filters_service, "service_client") as sc:
        sc.table.side_effect = [resume_chain, insert_chain]
        await filters_service.create_filter("u1", {"resume_id": "r1", "enabled": True})
    inserted = insert_chain.insert.call_args[0][0]
    assert inserted["text"] == "Frontend developer"


async def test_create_filter_does_not_override_client_text():
    from app.services import filters_service

    resume_chain = _fluent({
        "id": "r1", "title": "Frontend developer",
    })
    insert_chain = _fluent([{"id": "f1", "resume_id": "r1"}])
    with patch.object(filters_service, "service_client") as sc:
        sc.table.side_effect = [resume_chain, insert_chain]
        await filters_service.create_filter(
            "u1", {"resume_id": "r1", "text": "react"}
        )
    inserted = insert_chain.insert.call_args[0][0]
    assert inserted["text"] == "react"


async def test_create_filter_checks_resume_ownership_fail():
    from app.services import filters_service

    table = _fluent(None)  # maybe_single().execute() returns None data
    with patch.object(filters_service, "service_client") as sc:
        sc.table.return_value = table
        with pytest.raises(HTTPException) as exc:
            await filters_service.create_filter(
                "u1", {"resume_id": "r_other", "text": "x"}
            )
    assert exc.value.status_code == 400


async def test_update_filter_not_found():
    from app.services import filters_service

    table = _fluent([])  # no rows updated
    with patch.object(filters_service, "service_client") as sc:
        sc.table.return_value = table
        with pytest.raises(HTTPException) as exc:
            await filters_service.update_filter("u1", "missing", {"enabled": False})
    assert exc.value.status_code == 404


async def test_update_filter_empty_payload():
    from app.services import filters_service

    with pytest.raises(HTTPException) as exc:
        await filters_service.update_filter("u1", "fid", {})
    assert exc.value.status_code == 400


async def test_delete_filter_not_found():
    from app.services import filters_service

    table = _fluent([])
    with patch.object(filters_service, "service_client") as sc:
        sc.table.return_value = table
        with pytest.raises(HTTPException) as exc:
            await filters_service.delete_filter("u1", "missing")
    assert exc.value.status_code == 404


async def test_list_filters_returns_rows():
    from app.services import filters_service

    rows = [{
        "id": "f1", "resume_id": None, "text": "py", "area": 40,
        "experience": None, "work_format": None, "employment_form": None,
        "search_field": None, "period": None,
        "excluded_text": None, "enabled": True,
        "created_at": None,
    }]
    table = _fluent(rows)
    with patch.object(filters_service, "service_client") as sc:
        sc.table.return_value = table
        result = await filters_service.list_filters("u1")
    assert result == rows
