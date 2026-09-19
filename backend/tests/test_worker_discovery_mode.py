from unittest.mock import AsyncMock, MagicMock, patch


async def test_worker_flag_starts_discovery_and_scoring_not_legacy_apply():
    import worker_main

    registry = MagicMock()
    registry.active_user_ids.return_value = []
    registry.reconcile = AsyncMock()
    worker_main._next_discovery_at.clear()

    with (
        patch.object(worker_main, "_run_manual_search_job", new=AsyncMock(return_value=None)),
        patch.object(
            worker_main,
            "active_user_flags",
            return_value={"u1": (True, False)},
        ),
        patch.object(
            worker_main,
            "discover_user",
            new=AsyncMock(
                return_value={"sources": 1, "fetched": 2, "persisted": 2, "errors": 0}
            ),
        ) as discover,
        patch.object(
            worker_main,
            "score_user",
            new=AsyncMock(
                return_value={
                    "found": 2,
                    "scored": 2,
                    "hard_filtered": 0,
                    "archived": 0,
                    "errors": 0,
                    "retryable_errors": 0,
                    "skipped": 0,
                    "circuit_breaker": 0,
                }
            ),
        ) as score,
    ):
        await worker_main._reconcile(registry)

    discover.assert_awaited_once_with("u1")
    score.assert_awaited_once_with("u1")
    # Critical contract: legacy auto-apply loop is never started by worker_main.
    registry.reconcile.assert_awaited_once_with("u1", False, False)


async def test_discovery_and_scoring_are_not_repeated_on_every_15_second_reconcile():
    import worker_main

    registry = MagicMock()
    registry.active_user_ids.return_value = []
    registry.reconcile = AsyncMock()
    worker_main._next_discovery_at.clear()

    with (
        patch.object(worker_main, "_run_manual_search_job", new=AsyncMock(return_value=None)),
        patch.object(
            worker_main,
            "active_user_flags",
            return_value={"u1": (True, False)},
        ),
        patch.object(worker_main, "_monotonic", side_effect=[100.0, 101.0]),
        patch.object(
            worker_main,
            "discover_user",
            new=AsyncMock(
                return_value={"sources": 0, "fetched": 0, "persisted": 0, "errors": 0}
            ),
        ) as discover,
        patch.object(
            worker_main,
            "score_user",
            new=AsyncMock(
                return_value={
                    "found": 0,
                    "scored": 0,
                    "hard_filtered": 0,
                    "archived": 0,
                    "errors": 0,
                    "retryable_errors": 0,
                    "skipped": 0,
                    "circuit_breaker": 0,
                }
            ),
        ) as score,
    ):
        await worker_main._reconcile(registry)
        await worker_main._reconcile(registry)

    discover.assert_awaited_once_with("u1")
    score.assert_awaited_once_with("u1")


async def test_manual_job_runs_even_when_scheduled_discovery_is_disabled():
    import worker_main

    worker_main._next_discovery_at.clear()
    job = {"id": "run-1", "user_id": "u1", "status": "discovery"}
    discovery = {"sources": 1, "fetched": 3, "persisted": 2, "errors": 0}
    scoring = {
        "found": 2,
        "scored": 2,
        "hard_filtered": 0,
        "archived": 0,
        "errors": 0,
        "retryable_errors": 0,
        "skipped": 0,
        "circuit_breaker": 0,
    }

    with (
        patch.object(worker_main.search_run_service, "claim_next", new=AsyncMock(return_value=job)),
        patch.object(worker_main.search_run_service, "begin_scoring", new=AsyncMock(return_value={"status": "scoring"})) as begin,
        patch.object(worker_main.search_run_service, "complete", new=AsyncMock(return_value={"status": "completed"})) as complete,
        patch.object(worker_main, "discover_user", new=AsyncMock(return_value=discovery)) as discover,
        patch.object(worker_main, "score_user", new=AsyncMock(return_value=scoring)) as score,
        patch.object(worker_main, "_monotonic", return_value=100.0),
    ):
        user_id = await worker_main._run_manual_search_job()

    assert user_id == "u1"
    discover.assert_awaited_once_with("u1")
    begin.assert_awaited_once_with("run-1", discovery)
    score.assert_awaited_once_with("u1")
    complete.assert_awaited_once_with("run-1", discovery=discovery, scoring=scoring)
    assert worker_main._next_discovery_at["u1"] == 100.0 + worker_main.DISCOVERY_INTERVAL_S


async def test_manual_job_failure_is_persisted():
    import worker_main

    job = {"id": "run-1", "user_id": "u1", "status": "discovery"}
    with (
        patch.object(worker_main.search_run_service, "claim_next", new=AsyncMock(return_value=job)),
        patch.object(worker_main.search_run_service, "fail", new=AsyncMock()) as fail,
        patch.object(worker_main, "discover_user", new=AsyncMock(side_effect=RuntimeError("HH down"))),
    ):
        user_id = await worker_main._run_manual_search_job()

    assert user_id == "u1"
    assert fail.await_count == 1
    assert fail.await_args.args[0] == "run-1"
    assert "HH down" in str(fail.await_args.args[1])
