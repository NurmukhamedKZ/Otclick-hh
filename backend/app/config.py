from functools import cached_property

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

    # hh refresh-token cron: shared secret for /internal/cron/* + near-expiry window.
    # hh refresh token is single-use and only usable once the access token expired,
    # so the cron only refreshes creds expiring within this window (not all daily).
    INTERNAL_CRON_TOKEN: str = ""
    REFRESH_THRESHOLD_DAYS: int = 2

    # CloudPayments billing. PUBLIC_ID is sent to the widget; API_SECRET is the
    # HMAC key for webhook verification (Content-HMAC header) — never exposed.
    CLOUDPAYMENTS_PUBLIC_ID: str = ""
    CLOUDPAYMENTS_API_SECRET: str = ""
    PLAN_CURRENCY: str = "RUB"

    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-5.4-nano"
    OPENAI_RATE_LIMIT: int = 60

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @cached_property
    def fernet(self) -> Fernet:
        return Fernet(self.FERNET_KEY.encode())


settings = Settings()


# Paid plans offered in-app (mirror the landing pricing). Widget recurrent flag:
# charge every `period` `interval`(s). `period_days` drives the access window — the
# webhook derives it from the charged Amount (see billing._plan_for_amount).
PLANS: dict[str, dict] = {
    "sprint": {
        "id": "sprint",
        "name": "Otclick Спринт",
        "price": 1990,
        "interval": "Week",
        "period": 1,
        "period_days": 7,
    },
    "month": {
        "id": "month",
        "name": "Otclick Месяц",
        "price": 3900,
        "interval": "Month",
        "period": 1,
        "period_days": 30,
    },
}
DEFAULT_PLAN_ID = "month"
