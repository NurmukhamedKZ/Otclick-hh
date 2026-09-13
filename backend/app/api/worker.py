"""Worker control endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.services import filters_service, worker_control

router = APIRouter(prefix="/api/worker", tags=["worker"])


class StartResponse(BaseModel):
    state: str
    queued: int


class StopResponse(BaseModel):
    stopped: bool


class AgentStartResponse(BaseModel):
    agent_state: str


class AgentStopResponse(BaseModel):
    stopped: bool


class StatusResponse(BaseModel):
    state: str
    agent_state: str
    today_count: int
    daily_limit: int | None = None
    queued: int
    next_run_at: str | None
    last_error: str | None
    skipped_has_test: int = 0
    # Compatibility fields retained for existing frontend/API consumers.
    # The non-commercial build always runs in autonomous mode without quota.
    mode: str = "auto"
    limit_total: int | None = None
    total_used: int = 0


# The runners live in the standalone worker container, not this process — the
# dashboard only flips the persisted worker_enabled flag (worker_main reconciles
# within its poll interval). Status is derived from the flag + DB counters.
@router.post("/start", response_model=StartResponse)
async def start_worker(user_id: str = Depends(get_current_user)) -> StartResponse:
    if not await filters_service.has_active_filter(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Создайте хотя бы один фильтр с привязанным резюме перед запуском.",
        )
    await worker_control.set_enabled(user_id, True)
    # Раннер живёт в worker-контейнере и подхватит флаг на следующем цикле
    # (до POLL_INTERVAL_S), поэтому "running" здесь был бы враньём.
    return StartResponse(state="starting", queued=0)


@router.post("/stop", response_model=StopResponse)
async def stop_worker(user_id: str = Depends(get_current_user)) -> StopResponse:
    await worker_control.set_enabled(user_id, False)
    return StopResponse(stopped=True)


@router.post("/agent/start", response_model=AgentStartResponse)
async def start_agent(user_id: str = Depends(get_current_user)) -> AgentStartResponse:
    await worker_control.set_agent_enabled(user_id, True)
    return AgentStartResponse(agent_state="running")


@router.post("/agent/stop", response_model=AgentStopResponse)
async def stop_agent(user_id: str = Depends(get_current_user)) -> AgentStopResponse:
    await worker_control.set_agent_enabled(user_id, False)
    return AgentStopResponse(stopped=True)


@router.get("/status", response_model=StatusResponse)
async def worker_status(user_id: str = Depends(get_current_user)) -> StatusResponse:
    import asyncio

    from app.services import worker_runtime
    from app.worker.limiter import _read_day_count, _today_local, _tz_for_user, sent_total

    loop = asyncio.get_running_loop()

    def _today_count_db() -> int:
        tz = _tz_for_user(user_id)
        return _read_day_count(user_id, _today_local(tz))

    db_today, enabled, agent_enabled, rt, used_total = await asyncio.gather(
        loop.run_in_executor(None, _today_count_db),
        worker_control.is_enabled(user_id),
        worker_control.is_agent_enabled(user_id),
        worker_runtime.get(user_id),
        loop.run_in_executor(None, sent_total, user_id),
    )

    if enabled:
        # Нет строки heartbeat или она от прошлой остановленной сессии —
        # раннер ещё не поднялся.
        state = (rt or {}).get("state") or "starting"
        if state == "stopped":
            state = "starting"
    else:
        state = "stopped"

    agent_state = "running" if agent_enabled else "stopped"

    queued = int((rt or {}).get("queued") or 0) if enabled else 0
    next_run_at = (rt or {}).get("next_run_at") if enabled else None
    last_error = (rt or {}).get("last_error") if enabled else None

    return StatusResponse(
        state=state,
        agent_state=agent_state,
        today_count=db_today,
        daily_limit=None,
        queued=queued,
        next_run_at=next_run_at,
        last_error=last_error,
        mode="auto",
        limit_total=None,
        total_used=used_total,
    )
