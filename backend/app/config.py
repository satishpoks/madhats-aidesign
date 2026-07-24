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
    # Single image model — gemini-2.5-flash-image ("Nano Banana") for both tiers.
    # NB: gemini-3-pro-image ("Nano Banana Pro") is NOT served to this project —
    # generateContent hangs forever (never returns/errors), pinning jobs at
    # 'pending'. gemini-2.5-flash-image / gemini-3.1-flash-image both work.
    gemini_preview_model: str = "gemini-2.5-flash-image"
    gemini_final_model: str = "gemini-2.5-flash-image"

    # --- Email ---
    resend_api_key: str = ""
    resend_from_address: str = "studio@madhats.com.au"
    sales_notification_email: str = "sales@madhats.com.au"

    # --- Security ---
    admin_secret: str
    # Signs admin-user login JWTs. Defaults to admin_secret so existing
    # deployments need no new config; set a distinct value to decouple them.
    admin_jwt_secret: str = ""
    admin_jwt_ttl_seconds: int = 43200  # 12h admin session
    rate_limit_rpm: int = 10
    signed_url_ttl: int = 3600

    # --- AI usage caps (initial defaults; the app_settings DB row overrides) ---
    regen_edits_per_session: int = 3
    designs_per_customer_per_day: int = 2
    # CORS. "*" (the default) allows any origin — kept open/flexible for now.
    # Set a comma-separated origin list to lock it down later.
    allowed_origins: str = "*"
    verification_token_ttl_seconds: int = 900  # 15 min
    quote_token_ttl_seconds: int = 2592000  # 30 days — quote link stays valid a while

    # --- App ---
    app_env: str = "development"
    sentry_dsn: str = ""
    email_verify_base_url: str = "http://localhost:8000"
    # Customer-facing Studio (frontend) origin — used for the "make some edits"
    # link in the preview email, which reopens the chatbot on their session.
    studio_base_url: str = "http://localhost:5173"
    chatbot_persona_name: str = "Ricardo"

    # --- Orchestrator selection ---
    # When true, canvas sessions (flow_mode == "canvas") are handled by the
    # step-by-step v2 orchestrator. Every other session and the false case use
    # the v1 orchestrator, unchanged. Global flag; canvas-only in scope.
    canvas_orchestrator_v2: bool = False

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def allow_all_origins(self) -> bool:
        """True when CORS should accept any origin (ALLOWED_ORIGINS contains '*')."""
        return "*" in self.allowed_origins_list

    @property
    def rate_limit_str(self) -> str:
        """slowapi-format rate string, e.g. '10/minute'."""
        return f"{self.rate_limit_rpm}/minute"

    @property
    def admin_jwt_signing_key(self) -> str:
        """Key used to sign/verify admin JWTs — falls back to admin_secret."""
        return self.admin_jwt_secret or self.admin_secret


settings = Settings()  # type: ignore[call-arg]
