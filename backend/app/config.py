"""Application settings — the single place env vars are read and validated.

Startup fails fast (pydantic ValidationError) if any required var is missing.
No secret or model ID is ever hardcoded outside this module's defaults.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo-root .env (config.py -> app -> backend -> repo root). A backend-local
# .env, if present, overrides it. Real env vars (e.g. docker-compose) win over both.
_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_ROOT_ENV), ".env"),
        extra="ignore",
        case_sensitive=False,
    )

    # --- Supabase ---
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    supabase_storage_bucket: str = "madhats-assets"

    # --- Claude (conversation LLM) ---
    # Optional so the app can boot for local dev; required for live chatbot turns.
    anthropic_api_key: str = ""
    claude_haiku_model: str = "claude-haiku-4-5-20251001"

    # --- Image generation ---
    gemini_api_key: str = ""
    image_provider_preview: str = "stub"
    image_provider_final: str = "stub"
    gemini_preview_model: str = "gemini-2.0-flash-exp"
    gemini_final_model: str = "gemini-2.0-pro-exp"

    # --- Email ---
    resend_api_key: str = ""
    resend_from_address: str = "studio@madhats.com.au"
    sales_notification_email: str = "sales@madhats.com.au"

    # --- Security ---
    admin_secret: str
    rate_limit_rpm: int = 10
    signed_url_ttl: int = 3600
    allowed_origins: str = "http://localhost:5173"
    verification_token_ttl_seconds: int = 900  # 15 min

    # --- App ---
    app_env: str = "development"
    sentry_dsn: str = ""
    email_verify_base_url: str = "http://localhost:8000"
    chatbot_persona_name: str = "Ricardo"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def rate_limit_str(self) -> str:
        """slowapi-format rate string, e.g. '10/minute'."""
        return f"{self.rate_limit_rpm}/minute"


settings = Settings()  # type: ignore[call-arg]
