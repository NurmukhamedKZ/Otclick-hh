"""Standalone worker entrypoint for systemd / docker.

Polls profiles.worker_enabled every POLL_INTERVAL_S and reconciles runners:
start one for each enabled user with valid creds + plan, stop runners whose
user disabled the worker (or whose plan/creds lapsed). No auto-start at boot —
a user only gets a runner after pressing Start in the dashboard.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from dotenv import load_dotenv

load_dotenv()

from app.services.plan import filter_paid
from app.services.worker_control import active_user_flags
from app.worker.runner import get_registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("worker_main")

POLL_INTERVAL_S = 15


async def _reconcile(registry) -> None:
    loop = asyncio.get_running_loop()
    flags = await loop.run_in_executor(None, active_user_flags)
    paid = set(await loop.run_in_executor(None, filter_paid, list(flags.keys())))

    # Гейт остался только на агенте-рекрутёре: он по определению автономен, а
    # автономность — платная. Отклики бесплатный юзер шлёт сам, его ограничивают
    # лимиты в limiter, а не отказ на входе.
    desired: dict[str, tuple[bool, bool]] = {}
    for uid, (apply_on, agent_on) in flags.items():
        desired[uid] = (apply_on, agent_on and uid in paid)
    # Users with a live loop but no longer desired → reconcile to (False, False).
    for uid in registry.active_user_ids():
        desired.setdefault(uid, (False, False))

    for uid, (apply_on, agent_on) in desired.items():
        logger.info(
            "reconcile: user=%s apply=%s agent=%s", uid, apply_on, agent_on
        )
        await registry.reconcile(uid, apply_on, agent_on)


async def main() -> None:
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _request_stop(signame: str) -> None:
        logger.info("received %s — initiating shutdown", signame)
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_stop, sig.name)
        except NotImplementedError:
            # Windows doesn't implement loop.add_signal_handler — Ctrl+C still
            # raises KeyboardInterrupt into asyncio.run, which is fine here.
            pass

    registry = get_registry()
    # Inbound Telegram bot: lets the user answer/approve via inline buttons in
    # Telegram instead of the web UI. Optional and independent of the reconcile
    # loop; a failure here never affects apply/agent cycles.
    from app.services.telegram_notify import start_bot_loop, stop_bot_loop
    start_bot_loop(stop_event)
    logger.info("worker_main: reconcile loop start (every %ds)", POLL_INTERVAL_S)
    while not stop_event.is_set():
        try:
            await _reconcile(registry)
        except Exception:
            logger.exception("reconcile failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_S)
        except TimeoutError:
            pass

    logger.info("stopping all runners")
    await registry.stop_all()
    await stop_bot_loop()
    logger.info("worker_main shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
