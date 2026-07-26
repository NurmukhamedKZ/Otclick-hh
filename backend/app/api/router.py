from fastapi import APIRouter

from app.api import analytics, auth, billing, blacklist, captcha, chats, filters, forms, internal, qa, recruiter, resumes, webhooks, worker
from app.api import _debug
from app.config import settings

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(resumes.router)
api_router.include_router(filters.router)
api_router.include_router(worker.router)
api_router.include_router(captcha.router)
api_router.include_router(internal.router)
api_router.include_router(blacklist.router)
api_router.include_router(billing.router)
api_router.include_router(webhooks.router)
api_router.include_router(recruiter.router)
api_router.include_router(chats.router)
api_router.include_router(forms.router)
api_router.include_router(qa.router)
api_router.include_router(analytics.router)

if settings.DEBUG_ENDPOINTS:
    api_router.include_router(_debug.router)
