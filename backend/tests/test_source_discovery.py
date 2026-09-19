from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_discovery_stops_when_previous_head_is_reached_and_updates_stats():
    from app.services import source_discovery as sd

    source = {
        "id": "s1",
        "resume_id": "r1",
        "query_pairs": [{"key": "text", "value": "CIO"}],
        "cursor": {
            "head_ids": ["old-1", "old-2"],
            "stats": {"runs": 2, "fetched": 10, "persisted": 8, "skipped_applied": 2, "errors": 1},
        },
    }
    page = [
        {"id": "new-1", "name": "CIO", "employer": {"id": "1", "name": "A"}},
        {"id": "old-1", "name": "CIO old", "employer": {"id": "2", "name": "B"}},
        {"id": "older", "name": "older", "employer": {"id": "3", "name": "C"}},
    ]
    persisted: list[str] = []
    source_updates: list[dict] = []
    stat_updates: list[tuple[list[str], dict]] = []

    def fake_persist(**kwargs):
        persisted.append(str(kwargs["vacancy"]["id"]))
        return {"id": "p1"}

    def fake_update(source_id, **changes):
        assert source_id == "s1"
        source_updates.append(changes)

    def fake_stats(source_ids, **counts):
        stat_updates.append((source_ids, counts))

    with (
        patch.object(sd, "_search_page", new=AsyncMock(return_value=(page, 100))),
        patch.object(sd, "_existing_application_ids", return_value=set()),
        patch.object(sd, "_existing_pipeline_ids", return_value=set()),
        patch.object(sd, "persist_discovered", side_effect=fake_persist),
        patch.object(sd, "_update_source", side_effect=fake_update),
        patch.object(sd.source_statistics, "increment", side_effect=fake_stats),
    ):
        result = await sd.discover_source("u1", source)

    assert persisted == ["new-1"]
    assert result["overlap_found"] is True
    assert result["persisted"] == 1
    assert result["new"] == 1
    assert result["duplicate"] == 0
    assert stat_updates == [(["s1"], {"new": 1, "duplicate": 0})]
    final = source_updates[-1]
    assert final["cursor"]["version"] == 2
    assert final["cursor"]["head_ids"] == ["new-1", "old-1", "older"]
    assert final["cursor"]["stats"] == {
        "runs": 3,
        "fetched": 11,
        "persisted": 9,
        "skipped_applied": 2,
        "errors": 1,
    }
    assert final["cursor"]["last_run"]["persisted"] == 1
    assert final["cursor"]["last_run"]["new"] == 1
    assert final["cursor"]["last_run"]["duplicate"] == 0
    assert final["last_error"] is None


@pytest.mark.asyncio
async def test_discovery_counts_existing_pipeline_vacancy_as_duplicate():
    from app.services import source_discovery as sd

    source = {"id": "s1", "resume_id": "r1", "cursor": {}}
    page = [{"id": "123", "name": "CIO", "employer": {"id": "1", "name": "A"}}]
    stat_updates: list[dict] = []

    with (
        patch.object(sd, "_search_page", new=AsyncMock(return_value=(page, 1))),
        patch.object(sd, "_existing_application_ids", return_value=set()),
        patch.object(sd, "_existing_pipeline_ids", return_value={"123"}),
        patch.object(sd, "persist_discovered", return_value={"id": "p1"}),
        patch.object(sd, "_update_source"),
        patch.object(sd.source_statistics, "increment", side_effect=lambda ids, **counts: stat_updates.append(counts)),
    ):
        result = await sd.discover_source("u1", source)

    assert result["new"] == 0
    assert result["duplicate"] == 1
    assert stat_updates == [{"new": 0, "duplicate": 1}]


@pytest.mark.asyncio
async def test_discovery_error_increments_source_error_counter():
    from app.services import source_discovery as sd

    source = {
        "id": "s1",
        "cursor": {
            "head_ids": ["old"],
            "stats": {"runs": 4, "fetched": 20, "persisted": 12, "skipped_applied": 1, "errors": 2},
        },
    }
    updates: list[dict] = []

    def fake_update(source_id, **changes):
        updates.append(changes)

    with (
        patch.object(sd, "_search_page", new=AsyncMock(side_effect=RuntimeError("hh changed"))),
        patch.object(sd, "_update_source", side_effect=fake_update),
    ):
        with pytest.raises(RuntimeError):
            await sd.discover_source("u1", source)

    final = updates[-1]
    assert final["cursor"]["stats"]["runs"] == 5
    assert final["cursor"]["stats"]["errors"] == 3
    assert final["cursor"]["last_run"]["error"] == "hh changed"
    assert final["last_error"] == "hh changed"


def test_request_pairs_keep_duplicate_hh_parameters():
    from app.services.source_discovery import _request_pairs

    source = {
        "query_pairs": [
            {"key": "area", "value": "1"},
            {"key": "area", "value": "2"},
            {"key": "search_field", "value": "name"},
            {"key": "search_field", "value": "company_name"},
            {"key": "page", "value": "9"},
            {"key": "order_by", "value": "relevance"},
        ]
    }

    assert _request_pairs(source, 3) == [
        ("area", "1"),
        ("area", "2"),
        ("search_field", "name"),
        ("search_field", "company_name"),
        ("order_by", "publication_time"),
        ("page", "3"),
    ]
