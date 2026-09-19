from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

JobStatus = Literal["running", "captcha_required", "code_required", "success", "failed"]


class HHConnectRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str | None = None
    login_method: Literal["password", "email_code"] = "password"


class EnterCodeRequest(BaseModel):
    code: str = Field(min_length=1)


class HHConnectResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    screenshot_url: str | None = None
    error: str | None = None


class CaptchaSolveRequest(BaseModel):
    solution: str = Field(min_length=1)


class HHStatusResponse(BaseModel):
    connected: bool
    expires_at: datetime | None = None
    last_refreshed_at: datetime | None = None
    hh_user_id: str | None = None


class HHRefreshResponse(BaseModel):
    status: Literal["refreshed", "invalid", "error"]
    error: str | None = None
