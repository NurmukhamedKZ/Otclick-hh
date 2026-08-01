from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.schemas.auth import (
    CaptchaSolveRequest,
    EnterCodeRequest,
    HHConnectRequest,
    HHConnectResponse,
    HHRefreshResponse,
    HHStatusResponse,
    JobStatusResponse,
)
from app.services import hh_auth, token_refresh
from app.services.hh_credentials import HHCredentialsInvalid

router = APIRouter(prefix="/api/hh", tags=["hh"])


@router.post("/connect", response_model=HHConnectResponse)
async def connect(
    body: HHConnectRequest,
    user_id: str = Depends(get_current_user),
):
    if body.login_method == "email_code":
        if not body.username:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="username (email) is required",
            )
        job_id = await hh_auth.start_connect_email_code_job(user_id, body.username)
    else:
        if not body.password:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="password is required for password login method",
            )
        job_id = await hh_auth.start_connect_job(user_id, body.username, body.password)
    return HHConnectResponse(job_id=job_id, status="running")


@router.get("/connect/{job_id}", response_model=JobStatusResponse)
async def connect_status(
    job_id: str,
    user_id: str = Depends(get_current_user),
):
    state = hh_auth.get_job(job_id)
    if not state or state.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return JobStatusResponse(
        job_id=job_id,
        status=state.status,
        screenshot_url=state.screenshot_url,
        error=state.error,
    )


@router.post("/connect/{job_id}/captcha", status_code=status.HTTP_204_NO_CONTENT)
async def submit_captcha(
    job_id: str,
    body: CaptchaSolveRequest,
    user_id: str = Depends(get_current_user),
):
    state = hh_auth.get_job(job_id)
    if not state or state.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    if state.status != "captcha_required":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="captcha not pending")
    await hh_auth.solve_captcha(job_id, body.solution)


@router.post("/connect/{job_id}/code", status_code=status.HTTP_204_NO_CONTENT)
async def submit_email_code(
    job_id: str,
    body: EnterCodeRequest,
    user_id: str = Depends(get_current_user),
):
    state = hh_auth.get_job(job_id)
    if not state or state.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    if state.status != "code_required":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email code not expected (status is not code_required)",
        )
    await hh_auth.solve_email_code(job_id, body.code)


@router.post("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(user_id: str = Depends(get_current_user)):
    hh_auth.disconnect(user_id)


@router.post("/refresh", response_model=HHRefreshResponse)
async def refresh(user_id: str = Depends(get_current_user)):
    """Force-refresh access_token for the current user."""
    try:
        result = await token_refresh.refresh_user(user_id)
    except HHCredentialsInvalid as ex:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"hh credentials invalid: {ex.reason}",
        ) from ex
    return HHRefreshResponse(status=result["status"], error=result.get("error"))


@router.get("/status", response_model=HHStatusResponse)
async def hh_status(user_id: str = Depends(get_current_user)):
    return HHStatusResponse(**hh_auth.get_credentials_status(user_id))
