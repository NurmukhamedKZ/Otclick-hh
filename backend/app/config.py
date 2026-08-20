from functools import cached_property
from typing import Literal

from cryptography.fernet import Fernet
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # One env file for the whole repo (repo-root .env, same one compose reads).
    # "../.env" covers `cd backend && uvicorn`, ".env" covers running from root;
    # later entries win, so a backend-local .env still overrides if you keep one.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    SUPABASE_URL: str
    # Browser-reachable base URL of the same Supabase stack. In the local
    # docker-compose setup SUPABASE_URL is the in-network kong hostname, which
    # a browser can't resolve — signed Storage URLs must be rewritten to this.
    SUPABASE_PUBLIC_URL: str = "http://localhost:54321"
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str
    FERNET_KEY: str
    CORS_ORIGINS: str = "http://localhost:3000"
    DEBUG_ENDPOINTS: bool = False
    LOG_LEVEL: str = "INFO"

    # hh OAuth application. Empty → the official Android app's keys (see
    # app/hh/client_keys.py), which answer `geo_forbidden` outside their region.
    # Set all three together; HH_REDIRECT_URI must match the app's registration.
    HH_CLIENT_ID: str = ""
    HH_CLIENT_SECRET: str = ""
    HH_REDIRECT_URI: str = ""

    # hh refresh-token cron: shared secret for /internal/cron/* + near-expiry window.
    # hh refresh token is single-use and only usable once the access token expired,
    # so the cron only refreshes creds expiring within this window (not all daily).
    INTERNAL_CRON_TOKEN: str = ""
    REFRESH_THRESHOLD_DAYS: int = 2

    # Polar.sh billing (merchant of record). Prices, intervals and currency live
    # in the Polar products, not here — the code only knows product ids.
    POLAR_ACCESS_TOKEN: str = ""
    POLAR_WEBHOOK_SECRET: str = ""
    POLAR_SERVER: str = "sandbox"  # "sandbox" | "production"
    POLAR_SUCCESS_URL: str = "http://localhost:3000/billing/success"
    # Product ids differ between the sandbox and production organisations, so
    # they are env, not code. One per plan id in PLANS (POLAR_PRODUCT_<PLAN>).
    POLAR_PRODUCT_SPRINT: str = ""
    POLAR_PRODUCT_MONTH: str = ""
    PLAN_CURRENCY: str = "KZT"  # display only

    # Free tier vs paid. BILLING_ENABLED=False (self-host default) turns the
    # paywall off entirely: no caps, autonomous mode for everyone. Without it a
    # self-hoster would sit on 30 applies inside their own instance and could
    # only fix it by editing SQL.
    BILLING_ENABLED: bool = False
    FREE_TOTAL_APPLIES: int = 30      # lifetime, not per day
    PAID_DAILY_APPLIES: int = 100

    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-5.4-nano"
    OPENAI_RATE_LIMIT: int = 60

    # Positioning tactics baked into AI-generated candidate-facing text. See
    # docs/spec-ai-positioning.md. "full" opts into the guide's more
    # aggressive tactics (experience/age/education padding, phantom-offer
    # social proof) — deliberate user choice, not the default.
    AI_POSITIONING: Literal["balanced", "full"] = "balanced"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @cached_property
    def fernet(self) -> Fernet:
        return Fernet(self.FERNET_KEY.encode())


settings = Settings()


# Paid plans offered in-app. Price and interval live in the Polar product —
# duplicating them here is how you get two sources of truth that drift. `price`
# stays only because the UI prints it; the access window comes from the
# subscription's current_period_end, not from a local period_days.
# The Polar product id per plan lives in POLAR_PRODUCT_<PLAN> (see billing.py).
# `price` is in ₸ and is only printed in the UI — the charge itself comes from
# the Polar product, so these two must be kept in sync by hand.
PLANS: dict[str, dict] = {
    "sprint": {"id": "sprint", "name": "Otclick Спринт", "price": 1000},
    "month": {"id": "month", "name": "Otclick Месяц", "price": 3000},
}
DEFAULT_PLAN_ID = "month"
