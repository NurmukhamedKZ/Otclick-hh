"""Per-user auto-apply runner.

Loop: ensure queue has jobs (via producer) → check limits → throttle sleep →
apply_one → record. Captcha pauses indefinitely until external resume.
Retry: 1 on transient network/5xx, 0 on 4xx.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

import requests as _requests

from app.ai.agent import HHAgent
from app.hh import errors as hh_errors
from app.services import apply as apply_service
from app.services import captcha as captcha_service
from app.services import plan as plan_service
from app.services import worker_control
from app.services.hh_credentials import (
    load_api_client,
    mark_invalid,
    persist_if_refreshed,
)
from app.services.notifications import notify
from app.services.worker_runtime import heartbeat
from app.worker import limiter, throttle
from app.worker.queue import ApplyJob, drop_user_queue, get_user_queue
from app.worker.recruiter_poll import poll_recruiter_chats

logger = logging.getLogger(__name__)

State = Literal["running", "paused_captcha", "paused_limit", "idle", "stopped"]

# Sleep when producer found 0 jobs and we're idle. Backs off exponentially:
# each empty producer run scans up to MAX_PAGES_PER_FILTER pages *per filter*,
# so retrying every 10s in the steady state is a continuous flood of
# GET /vacancies at hh — the fastest way to get a user's account flagged.
IDLE_REFILL_SLEEP_S = 10
IDLE_REFILL_MAX_SLEEP_S = 15 * 60

# Pause before retrying an apply that hh answered with 429.
RETRY_THROTTLED_SLEEP_S = 60

# Plan-B captcha poll interval (seconds) — re-probe GET /me while paused.
CAPTCHA_POLL_S = 5

# Recruiter chat poll cadence — runs in its own task, independent of apply limits.
RECRUITER_POLL_INTERVAL_S = 120


@dataclass
class RunnerHandle:
    user_id: str
    state: State = "running"
    today_count: int = 0
    next_run_at: datetime | None = None
    task: asyncio.Task | None = None
    recruiter_task: asyncio.Task | None = None
    captcha_event: asyncio.Event = field(default_factory=asyncio.Event)
    agent_stop: asyncio.Event = field(default_factory=asyncio.Event)
    cluster: throttle.SessionCluster = field(default_factory=throttle.SessionCluster)
    agent: HHAgent | None = None
    last_error: str | None = None
    skipped_has_test: int = 0

    def __post_init__(self) -> None:
        if self.agent is None:
            self.agent = HHAgent(self.user_id)


def _is_transient(ex: BaseException) -> bool:
    if isinstance(ex, hh_errors.InternalServerError):  # also catches BadGateway
        return True
    if isinstance(ex, hh_errors.TooManyRequests):
        return True
    if isinstance(ex, (_requests.ConnectionError, _requests.Timeout)):
        return True
    return False


def _retry_delay(ex: BaseException) -> float:
    """Pause before the single retry — 429 needs to actually back off."""
    return RETRY_THROTTLED_SLEEP_S if isinstance(ex, hh_errors.TooManyRequests) else 5.0


async def _maybe_apply_with_retry(
    job: ApplyJob, agent: HHAgent
) -> apply_service.ApplyStatus:
    try:
        return await apply_service.apply_one(
            job.user_id, job.resume_id, job.vacancy_id, agent, job.filter_id
        )
    except Exception as ex:
        if not _is_transient(ex):
            logger.exception("apply_one fatal for %s/%s", job.user_id, job.vacancy_id)
            return "failed"
        delay = _retry_delay(ex)
        logger.warning(
            "apply_one transient (%s) for %s/%s — retry once in %.0fs",
            type(ex).__name__,
            job.user_id,
            job.vacancy_id,
            delay,
        )
        await asyncio.sleep(delay)
    try:
        return await apply_service.apply_one(
            job.user_id, job.resume_id, job.vacancy_id, agent, job.filter_id
        )
    except Exception:
        logger.exception(
            "apply_one retry failed for %s/%s", job.user_id, job.vacancy_id
        )
        return "failed"


async def _disable_worker(user_id: str) -> None:
    """Погасить персистентный флаг после терминальной остановки.

    Без этого worker_main видит worker_enabled=true, каждые POLL_INTERVAL_S
    поднимает раннер заново, тот снова упирается в мёртвый токен и снова шлёт
    уведомление — бесконечный цикл.
    """
    try:
        await worker_control.set_enabled(user_id, False)
    except Exception:
        logger.warning("failed to clear worker_enabled for %s", user_id, exc_info=True)


async def _finish_batch(handle: RunnerHandle) -> None:
    """Ручной режим отработал пачку: погасить флаг и встать.

    Флаг гасим первым — иначе worker_main на следующем цикле увидит
    worker_enabled=true, поднимет раннер заново, и «один проход» превратится
    в ту же бесконечную петлю, только с паузой в POLL_INTERVAL_S.
    """
    handle.state = "idle"
    handle.next_run_at = None
    await worker_control.set_enabled(handle.user_id, False)
    await heartbeat(
        handle.user_id,
        state="idle",
        queued=0,
        today_count=handle.today_count,
        next_run_at=None,
        last_error=handle.last_error,
    )
    logger.info("user %s: manual batch done — stopping", handle.user_id)


async def _probe_me(user_id: str) -> str:
    """Probe GET /me to detect whether the hh captcha lifted.

    Returns 'ok' (clear), 'captcha' (still blocked / transient — keep polling),
    'token_dead' (creds unusable — stop), or 'banned' (account blocked — stop).
    """
    loop = asyncio.get_running_loop()
    try:
        client = await load_api_client(user_id)
    except Exception:
        logger.warning(
            "probe_me: cannot load creds for %s — token_dead", user_id, exc_info=True
        )
        return "token_dead"
    original = client.access_token
    try:
        await loop.run_in_executor(None, lambda: client.get("me"))
        return "ok"
    except hh_errors.CaptchaRequired:
        return "captcha"
    except hh_errors.Forbidden as ex:
        if apply_service.is_ban_error(ex):
            await mark_invalid(user_id, f"account banned (/me probe): {ex}")
            return "banned"
        await mark_invalid(user_id, f"Forbidden on /me probe: {ex}")
        return "token_dead"
    except Exception:
        logger.warning(
            "probe_me: transient error for %s — keep polling", user_id, exc_info=True
        )
        return "captcha"
    finally:
        await persist_if_refreshed(user_id, client, original)


def _seconds_until_next_local_midnight(user_id: str) -> float:
    tz = limiter._tz_for_user(user_id)  # ok — both worker module
    now = datetime.now(tz)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=10, microsecond=0)
    return max(60.0, (tomorrow - now).total_seconds())


async def _run_loop(handle: RunnerHandle) -> None:
    from app.services.vacancy_producer import produce_jobs  # local import: avoid cycle

    user_id = handle.user_id
    queue = get_user_queue(user_id)
    rng = random.Random()
    idle_sleep = IDLE_REFILL_SLEEP_S
    # Free tier runs one batch by hand and stops; paid loops forever. Read once —
    # a plan change mid-batch takes effect on the next start, which is fine.
    limits = await plan_service.get_limits(user_id)
    manual = limits["mode"] == "manual"
    produced_once = False
    logger.info("runner: user=%s loop START (mode=%s)", user_id, limits["mode"])

    async def _hb() -> None:
        await heartbeat(
            user_id,
            state=handle.state,
            queued=queue.qsize(),
            today_count=handle.today_count,
            next_run_at=handle.next_run_at,
            last_error=handle.last_error,
        )

    await _hb()
    while True:
        logger.debug(
            "runner: user=%s tick state=%s queue=%d today=%d",
            user_id, handle.state, queue.qsize(), handle.today_count,
        )
        # Captcha pause — wait until external resume sets event.
        if handle.state == "paused_captcha":
            handle.next_run_at = None
            while handle.state == "paused_captcha":
                try:
                    await asyncio.wait_for(
                        handle.captcha_event.wait(), timeout=CAPTCHA_POLL_S
                    )
                except TimeoutError:
                    pass
                handle.captcha_event.clear()
                if handle.state != "paused_captcha":
                    break
                result = await _probe_me(user_id)
                if result == "ok":
                    await captcha_service.mark_solved(user_id)
                    await notify(user_id, "captcha", {"resolved": True})
                    handle.state = "running"
                    await _hb()
                    logger.info("user %s: captcha cleared — resuming", user_id)
                elif result == "token_dead":
                    handle.state = "stopped"
                    handle.last_error = "hh token dead — reconnect required"
                    await notify(user_id, "token_dead", {})
                    await notify(user_id, "worker_stop", {"reason": "token_dead"})
                    await _disable_worker(user_id)
                    await _hb()
                    logger.error(
                        "user %s: token dead during captcha probe — stopping", user_id
                    )
                    return
                elif result == "banned":
                    handle.state = "stopped"
                    handle.last_error = "hh account banned"
                    await notify(user_id, "account_banned", {})
                    await notify(user_id, "worker_stop", {"reason": "account_banned"})
                    await _disable_worker(user_id)
                    await _hb()
                    logger.error(
                        "user %s: account banned during captcha probe — stopping", user_id
                    )
                    return
                # "captcha" → keep polling
            if handle.state == "stopped":
                return

        # Limits.
        check = await limiter.check(user_id)
        if check == "limit_total":
            # Бесплатный тир исчерпан навсегда — спать до полуночи бессмысленно.
            # Флаг гасим, иначе worker_main поднимает раннер каждые POLL_INTERVAL_S
            # и уведомление уходит по кругу.
            handle.state = "stopped"
            handle.last_error = "free limit reached"
            handle.next_run_at = None
            await notify(user_id, "limit_total", {"limit": limits["total"]})
            await _disable_worker(user_id)
            await _hb()
            logger.info("user %s: free total limit reached — stopping", user_id)
            return
        if check == "limit_day":
            handle.state = "paused_limit"
            handle.last_error = "daily limit"
            sleep_s = await asyncio.get_running_loop().run_in_executor(
                None, _seconds_until_next_local_midnight, user_id
            )
            handle.next_run_at = datetime.now(UTC) + timedelta(seconds=sleep_s)
            await notify(
                user_id, "limit_reached", {"source": "local_day", "sleep_s": int(sleep_s)}
            )
            await _hb()
            logger.info("user %s: daily limit, sleeping %.0fs", user_id, sleep_s)
            await asyncio.sleep(sleep_s)
            handle.state = "running"
            handle.last_error = None
            await _hb()
            continue
        # Refill queue when empty.
        if queue.empty():
            if manual and produced_once:
                # Пачка отработана — в ручном режиме на этом всё.
                await _finish_batch(handle)
                return
            try:
                pushed, skipped_has_test = await produce_jobs(user_id, handle.agent)
            except Exception:
                logger.exception("producer failed for %s", user_id)
                pushed, skipped_has_test = 0, 0
            produced_once = True
            handle.skipped_has_test += skipped_has_test
            await _hb()
            if pushed == 0:
                if manual:
                    await _finish_batch(handle)
                    return
                handle.next_run_at = datetime.now(UTC) + timedelta(
                    seconds=idle_sleep
                )
                logger.info(
                    "user %s: no new vacancies, sleeping %ds", user_id, idle_sleep
                )
                await _hb()
                await asyncio.sleep(idle_sleep)
                idle_sleep = min(idle_sleep * 2, IDLE_REFILL_MAX_SLEEP_S)
                continue
            idle_sleep = IDLE_REFILL_SLEEP_S

        # Session cluster break — up to 2h, so publish it before sleeping or the
        # UI shows "работает" for the whole break.
        if handle.cluster.should_break():
            break_s = handle.cluster.next_break_seconds()
            handle.next_run_at = datetime.now(UTC) + timedelta(seconds=break_s)
            logger.info("user %s: cluster break %.0fs", user_id, break_s)
            await _hb()
            await asyncio.sleep(break_s)
            handle.next_run_at = None
            await _hb()

        # Pull next job.
        try:
            job = await asyncio.wait_for(queue.get(), timeout=30.0)
        except TimeoutError:
            logger.debug("runner: user=%s queue.get() timeout — re-loop", user_id)
            continue

        # Throttle pre-apply.
        delay = throttle.next_delay(rng)
        handle.next_run_at = datetime.now(UTC) + timedelta(seconds=delay)
        logger.info(
            "runner: user=%s applying vacancy=%s (resume=%s) after %.1fs delay",
            user_id, job.vacancy_id, job.resume_id, delay,
        )
        await asyncio.sleep(delay)

        status = await _maybe_apply_with_retry(job, handle.agent)
        logger.info(
            "runner: user=%s vacancy=%s status=%s", user_id, job.vacancy_id, status
        )
        await _hb()

        if status in ("sent", "form_sent"):
            handle.today_count = await limiter.increment(user_id)
            handle.cluster.record_apply()
        elif status == "captcha":
            handle.state = "paused_captcha"
            handle.captcha_event.clear()
            handle.last_error = f"captcha on vacancy {job.vacancy_id}"
            logger.warning("user %s: captcha — pausing", user_id)
            await notify(user_id, "captcha", {"vacancy_id": job.vacancy_id})
            await _hb()
        elif status == "limit_day":
            # hh told us we're done for the day — bump local to cap, then pause.
            handle.state = "paused_limit"
            sleep_s = await asyncio.get_running_loop().run_in_executor(
                None, _seconds_until_next_local_midnight, user_id
            )
            handle.next_run_at = datetime.now(UTC) + timedelta(seconds=sleep_s)
            handle.last_error = "hh daily limit"
            await notify(
                user_id, "limit_reached", {"source": "hh", "sleep_s": int(sleep_s)}
            )
            await _hb()
            logger.info(
                "user %s: hh LimitExceeded, sleeping %.0fs", user_id, sleep_s
            )
            await asyncio.sleep(sleep_s)
            handle.state = "running"
            handle.last_error = None
            await _hb()
        elif status == "token_dead":
            handle.state = "stopped"
            handle.last_error = "hh token dead — reconnect required"
            await notify(user_id, "token_dead", {"vacancy_id": job.vacancy_id})
            await notify(user_id, "worker_stop", {"reason": "token_dead"})
            await _disable_worker(user_id)
            logger.error("user %s: token dead — stopping runner", user_id)
            await _hb()
            return
        elif status == "account_banned":
            handle.state = "stopped"
            handle.last_error = "hh account banned"
            await notify(user_id, "account_banned", {"vacancy_id": job.vacancy_id})
            await notify(user_id, "worker_stop", {"reason": "account_banned"})
            await _disable_worker(user_id)
            await _hb()
            logger.error("user %s: account banned — stopping runner", user_id)
            return
        elif status == "form_required" or status == "form_pending":
            handle.skipped_has_test += 1
        elif status == "vacancy_gone":
            pass
        elif status == "resume_missing":
            handle.last_error = f"resume {job.resume_id} missing"
            await notify(
                user_id,
                "resume_missing",
                {"resume_id": job.resume_id, "vacancy_id": job.vacancy_id},
            )
        elif status == "failed":
            handle.last_error = f"failed on vacancy {job.vacancy_id}"


async def _recruiter_loop(handle: RunnerHandle) -> None:
    """Answer recruiter chats on a fixed cadence, independent of the apply loop.

    Runs as its own task with its own on/off signal (`agent_stop`), so the AI
    agent can run with auto-apply off (and vice versa). Daily apply caps
    and empty-queue idle never stop recruiter replies.
    """
    user_id = handle.user_id
    logger.info("recruiter loop: user=%s START", user_id)
    while not handle.agent_stop.is_set():
        try:
            await poll_recruiter_chats(user_id, handle.agent)
        except Exception:
            logger.exception("recruiter poll failed for %s", user_id)
        try:
            await asyncio.wait_for(
                handle.agent_stop.wait(), timeout=RECRUITER_POLL_INTERVAL_S
            )
        except TimeoutError:
            pass
    logger.info("recruiter loop: user=%s STOP", user_id)


def _spawn_apply(handle: RunnerHandle) -> None:
    user_id = handle.user_id
    logger.info("registry: spawning apply runner for user=%s", user_id)
    handle.state = "running"
    handle.task = asyncio.create_task(_run_loop(handle), name=f"worker:{user_id}")

    def _on_done(t: asyncio.Task, uid: str = user_id) -> None:
        if t.cancelled():
            logger.info("runner: user=%s task cancelled", uid)
            return
        exc = t.exception()
        if exc is not None:
            logger.error("runner: user=%s task crashed: %r", uid, exc, exc_info=exc)
        else:
            logger.info("runner: user=%s task ended cleanly", uid)

    handle.task.add_done_callback(_on_done)


def _spawn_agent(handle: RunnerHandle) -> None:
    user_id = handle.user_id
    logger.info("registry: spawning recruiter agent for user=%s", user_id)
    handle.agent_stop.clear()
    handle.recruiter_task = asyncio.create_task(
        _recruiter_loop(handle), name=f"recruiter:{user_id}"
    )

    def _on_recruiter_done(t: asyncio.Task, uid: str = user_id) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error("recruiter: user=%s task crashed: %r", uid, exc, exc_info=exc)

    handle.recruiter_task.add_done_callback(_on_recruiter_done)


async def _cancel_apply(handle: RunnerHandle) -> None:
    handle.state = "stopped"
    task = handle.task
    handle.task = None
    if task:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    drop_user_queue(handle.user_id)


async def _cancel_agent(handle: RunnerHandle) -> None:
    handle.agent_stop.set()
    task = handle.recruiter_task
    handle.recruiter_task = None
    if task:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


class WorkerRegistry:
    def __init__(self) -> None:
        self._handles: dict[str, RunnerHandle] = {}
        self._lock = asyncio.Lock()

    async def reconcile(
        self, user_id: str, want_apply: bool, want_agent: bool
    ) -> RunnerHandle | None:
        """Start/stop the apply loop and recruiter loop independently."""
        async with self._lock:
            handle = self._handles.get(user_id)
            apply_live = bool(handle and handle.task and not handle.task.done())
            agent_live = bool(
                handle and handle.recruiter_task and not handle.recruiter_task.done()
            )

            if not want_apply and not want_agent:
                if handle:
                    await _cancel_apply(handle)
                    await _cancel_agent(handle)
                    self._handles.pop(user_id, None)
                    try:
                        await heartbeat(
                            user_id, state="stopped", queued=0, next_run_at=None
                        )
                    except Exception:
                        logger.warning(
                            "worker_runtime stop heartbeat failed for %s",
                            user_id,
                            exc_info=True,
                        )
                return None

            if handle is None:
                handle = RunnerHandle(user_id=user_id)
                self._handles[user_id] = handle

            if want_apply and not apply_live:
                _spawn_apply(handle)
            elif not want_apply and apply_live:
                await _cancel_apply(handle)

            if want_agent and not agent_live:
                _spawn_agent(handle)
            elif not want_agent and agent_live:
                await _cancel_agent(handle)

            return handle

    async def start(self, user_id: str) -> RunnerHandle:
        """Legacy: start both loops (apply + recruiter agent)."""
        handle = await self.reconcile(user_id, True, True)
        assert handle is not None
        return handle

    async def stop(self, user_id: str) -> bool:
        async with self._lock:
            handle = self._handles.pop(user_id, None)
        if not handle:
            drop_user_queue(user_id)
            return False
        await _cancel_apply(handle)
        await _cancel_agent(handle)
        drop_user_queue(user_id)
        try:
            await heartbeat(user_id, state="stopped", queued=0, next_run_at=None)
        except Exception:
            logger.warning("worker_runtime stop heartbeat failed for %s", user_id, exc_info=True)
        return True

    def get(self, user_id: str) -> RunnerHandle | None:
        handle = self._handles.get(user_id)
        if handle and handle.task and handle.task.done():
            handle.state = "stopped"
        return handle

    def running_user_ids(self) -> list[str]:
        """Users with a live (not-done) apply task — for worker_main reconcile."""
        return [
            uid
            for uid, h in self._handles.items()
            if h.task is not None and not h.task.done()
        ]

    def active_user_ids(self) -> list[str]:
        """Users with any live loop (apply or recruiter agent)."""
        out: list[str] = []
        for uid, h in self._handles.items():
            apply_live = h.task is not None and not h.task.done()
            agent_live = h.recruiter_task is not None and not h.recruiter_task.done()
            if apply_live or agent_live:
                out.append(uid)
        return out

    def resume_captcha(self, user_id: str) -> bool:
        handle = self._handles.get(user_id)
        if not handle or handle.state != "paused_captcha":
            return False
        handle.captcha_event.set()
        return True

    async def stop_all(self) -> None:
        for user_id in list(self._handles.keys()):
            await self.stop(user_id)


_registry: WorkerRegistry | None = None


def get_registry() -> WorkerRegistry:
    global _registry
    if _registry is None:
        _registry = WorkerRegistry()
    return _registry


def reset_registry() -> None:
    """Test hook."""
    global _registry
    _registry = None
