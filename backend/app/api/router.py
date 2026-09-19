from fastapi import APIRouter

from app.api import (
    _debug,
    analytics,
    auth,
    blacklist,
    candidate_context,
    captcha,
    chats,
    extension,
    filters,
    forms,
    internal,
    qa,
    recruiter,
    resumes,
    search_sources,
    selection_rules,
    send_queue,
    vacancies,
    worker,
)
from app.config import settings

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(resumes.router)
api_router.include_router(filters.router)
api_router.include_router(candidate_context.router)
api_router.include_router(search_sources.router)
api_router.include_router(vacancies.router)
api_router.include_router(selection_rules.router)
api_router.include_router(send_queue.router)
api_router.include_router(worker.router)
api_router.include_router(captcha.router)
api_router.include_router(internal.router)
api_router.include_router(blacklist.router)
api_router.include_router(recruiter.router)
api_router.include_router(chats.router)
api_router.include_router(forms.router)
api_router.include_router(qa.router)
api_router.include_router(analytics.router)
api_router.include_router(extension.router)

if settings.DEBUG_ENDPOINTS:
    api_router.include_router(_debug.router)
