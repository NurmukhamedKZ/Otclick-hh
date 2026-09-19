"""Standalone worker entrypoint for systemd / docker.

Manual `run-now` requests are durable `search_runs` jobs. Vacancy scoring itself
uses leased claims; every reconcile pass recovers expired claims before taking
new work so a killed worker cannot strand a vacancy forever.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time

from dotenv import load_dotenv

load_dotenv()

from app.services import search_run_service
from app.services.pipeline_scoring import reap_stale_scoring, score_user
from app.services.source_discovery import discover_user
from app.services.worker_control import active_user_flags
from app.worker.runner import get_registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("worker_main")

POLL_INTERVAL_S = 15
DISCOVERY_INTERVAL_S = 5 * 60
_next_discovery_at: dict[str, float] = {}
_monotonic = time.monotonic


async def _run_discovery_if_due(user_id: str, enabled: bool) -> None:
    if not enabled:
        _next_discovery_at.pop(user_id, None)
        return
    now = _monotonic()
    if now < _next_discovery_at.get(user_id, 0.0):
        return
    _next_discovery_at[user_id] = now + DISCOVERY_INTERVAL_S
    try:
        discovery_summary = await discover_user(user_id)
    except Exception:
        logger.exception("discovery failed for user=%s", user_id)
        return
    logger.info("discovery complete user=%s summary=%s", user_id, discovery_summary)

    try:
        scoring_summary = await score_user(user_id)
    except Exception:
        logger.exception("scoring batch failed for user=%s", user_id)
        return
    logger.info("scoring complete user=%s summary=%s", user_id, scoring_summary)


async def _run_manual_search_job() -> str | None:
    job = await search_run_service.claim_next()
    if not job:
        return None

    run_id = str(job["id"])
    user_id = str(job["user_id"])
    discovery_summary: dict | None = None
    logger.info("manual search run start run=%s user=%s", run_id, user_id)
    try:
        discovery_summary = await discover_user(user_id)
        changed = await search_run_service.begin_scoring(run_id, discovery_summary)
        if not changed:
            raise RuntimeError("manual search run changed before scoring")

        scoring_summary = await score_user(user_id)
        await search_run_service.complete(
            run_id,
            discovery=discovery_summary,
            scoring=scoring_summary,
        )
        _next_discovery_at[user_id] = _monotonic() + DISCOVERY_INTERVAL_S
        logger.info(
            "manual search run complete run=%s user=%s discovery=%s scoring=%s",
            run_id,
            user_id,
            discovery_summary,
            scoring_summary,
        )
    except Exception as ex:
        await search_run_service.fail(run_id, ex, discovery=discovery_summary)
        logger.exception("manual search run failed run=%s user=%s", run_id, user_id)
    return user_id


async def _reconcile(registry) -> None:
    try:
        recovered = await reap_stale_scoring()
        if recovered:
            logger.warning("recovered %s expired vacancy scoring lease(s)", recovered)
    except Exception:
        # Recovery failure must be visible but must not take the whole worker down.
        logger.exception("vacancy scoring lease recovery failed")

    manual_user = await _run_manual_search_job()

    loop = asyncio.get_running_loop()
    flags = await loop.run_in_executor(None, active_user_flags)

    desired_agent: dict[str, bool] = {}
    for uid, (discovery_on, agent_on) in flags.items():
        desired_agent[uid] = agent_on
        if uid != manual_user:
            await _run_discovery_if_due(uid, discovery_on)

    for uid in registry.active_user_ids():
        desired_agent.setdefault(uid, False)

    for uid, agent_on in desired_agent.items():
        logger.info(
            "reconcile: user=%s discovery=%s agent=%s",
            uid,
            bool(flags.get(uid, (False, False))[0]),
            agent_on,
        )
        await registry.reconcile(uid, False, agent_on)


async def main() -> None:
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _request_stop(signame: str) -> None:
        logger.info("received %s — initiating shutdown", signame)
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _request_stop, sig.name)

    registry = get_registry()
    logger.info(
        "worker_main: discovery/scoring/recruiter reconcile loop start (every %ds)",
        POLL_INTERVAL_S,
    )
    while not stop_event.is_set():
        try:
            await _reconcile(registry)
        except Exception:
            logger.exception("reconcile failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_S)
        except TimeoutError:
            pass

    logger.info("stopping recruiter/legacy runners")
    await registry.stop_all()
    logger.info("worker_main shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
