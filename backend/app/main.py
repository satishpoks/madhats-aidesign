"""FastAPI application entrypoint.

Wires CORS, Sentry, structlog, slowapi rate limiting, and all routers.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import sentry_sdk
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.deps import limiter
from app.api.routes import (
    admin_decoration_types,
    admin_deliveries,
    admin_diagnostics,
    admin_generations,
    admin_graphics,
    admin_hat_types,
    admin_leads,
    admin_prompt,
    admin_settings,
    admin_stores,
    chat,
    composite,
    decoration_types,
    generate,
    graphics,
    hat_types,
    health,
    leads,
    media,
    products,
    quote,
    sessions,
    submissions,
    uploads,
)
from app.config import settings


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )


def _rate_limit_handler(request, exc):  # noqa: ANN001
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


def build_cors_kwargs(cfg) -> dict:  # noqa: ANN001
    """CORSMiddleware kwargs for the given settings.

    When ALLOWED_ORIGINS contains "*" (the current default) we reflect any
    request origin via a catch-all regex rather than emitting a literal "*",
    because browsers reject Access-Control-Allow-Origin: * together with
    allow_credentials=True. Otherwise CORS is locked to the configured list.
    """
    kwargs: dict = {
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }
    if cfg.allow_all_origins:
        kwargs["allow_origin_regex"] = ".*"
    else:
        kwargs["allow_origins"] = cfg.allowed_origins_list
    return kwargs


@asynccontextmanager
async def lifespan(app: FastAPI):
    log = structlog.get_logger()
    log.info("startup", env=settings.app_env)
    yield
    log.info("shutdown")


def create_app() -> FastAPI:
    _configure_logging()

    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.app_env,
            send_default_pii=False,  # never ship PII to Sentry
            traces_sample_rate=0.1,
        )

    app = FastAPI(title="MadHats AI Design Studio", version="0.1.0", lifespan=lifespan)

    # rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)

    # CORS — see build_cors_kwargs (open to all origins while ALLOWED_ORIGINS="*").
    app.add_middleware(CORSMiddleware, **build_cors_kwargs(settings))

    for router in (
        health.router,
        products.router,
        hat_types.router,
        graphics.router,
        decoration_types.router,
        admin_decoration_types.router,
        sessions.router,
        chat.router,
        composite.router,
        uploads.router,
        generate.router,
        leads.router,
        media.router,
        quote.router,
        submissions.router,
        admin_stores.router,
        admin_deliveries.router,
        admin_generations.router,
        admin_leads.router,
        admin_prompt.router,
        admin_diagnostics.router,
        admin_settings.router,
        admin_hat_types.router,
        admin_graphics.router,
    ):
        app.include_router(router)

    return app


app = create_app()
