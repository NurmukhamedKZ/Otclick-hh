import logging

from dotenv import load_dotenv

load_dotenv()

from app.api.router import api_router
from app.config import settings
from app.db.supabase import service_client
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# Quiet down noisy libs even at DEBUG level.
for noisy in ("httpx", "httpcore", "hpack", "urllib3", "supabase"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

app = FastAPI(title="AIautoclicker API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
def health():
    # 503 on a dead DB — a 200 here makes the docker healthcheck (and every
    # orchestrator above it) call a broken API healthy, and `worker` starts on
    # `depends_on: api: service_healthy`.
    try:
        service_client.table("profiles").select("id").limit(1).execute()
    except Exception:
        logging.getLogger(__name__).warning("health: db check failed", exc_info=True)
        raise HTTPException(status_code=503, detail={"status": "degraded", "db": False})
    return {"status": "ok", "db": True}
