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
    admin_deliveries,
    admin_diagnostics,
    admin_hat_types,
    admin_leads,
    admin_prompt,
    admin_settings,
    admin_stores,
    chat,
    generate,
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

    # CORS — locked to configured origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in (
        health.router,
        products.router,
        hat_types.router,
        sessions.router,
        chat.router,
        uploads.router,
        generate.router,
        leads.router,
        media.router,
        quote.router,
        submissions.router,
        admin_stores.router,
        admin_deliveries.router,
        admin_leads.router,
        admin_prompt.router,
        admin_diagnostics.router,
        admin_settings.router,
        admin_hat_types.router,
    ):
        app.include_router(router)

    return app


app = create_app()
