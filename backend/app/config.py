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

    # Hard safety gate for every real vacancy response. Development, discovery,
    # scoring and review must work with this false. Enabling it is necessary but
    # not sufficient for the new funnel: a send job still needs explicit approval.
    ALLOW_REAL_APPLY: bool = False

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

    # Generic OpenAI-compatible chat endpoint. The endpoint may be OpenAI itself,
    # OpenCode Go, LongCat direct, or another provider implementing the protocol.
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-5.4-nano"
    OPENAI_RATE_LIMIT: int = 60
    # function_calling is the portable default. json_schema can be selected for
    # providers that explicitly support OpenAI Structured Outputs.
    OPENAI_STRUCTURED_OUTPUT_METHOD: Literal[
        "function_calling", "json_mode", "json_schema"
    ] = "function_calling"

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
