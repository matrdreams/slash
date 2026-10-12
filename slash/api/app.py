"""FastAPI application. OpenAPI is served at /openapi.json."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from slash import __version__
from slash.api.routes import devices, sessions, takeover, tasks
from slash.core.errors import (
    AdbError,
    BootTimeoutError,
    BudgetExceeded,
    ConflictError,
    InvalidTransition,
    NotFoundError,
    PolicyViolation,
    ResidencyError,
    SignatureMismatchError,
    SlashError,
    TokenError,
)
from slash.core.models import TaskStatus

log = logging.getLogger("slash")


def create_app(ctx, *, start_background: bool = False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        if start_background:
            task = asyncio.create_task(_background(app.state.ctx))
        yield
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(
        title="slash",
        version=__version__,
        description="Self-hosted Android agent control plane for Redroid.",
        lifespan=lifespan,
    )
    app.state.ctx = ctx
    app.include_router(devices.router, prefix="/api/v1")
    app.include_router(tasks.router, prefix="/api/v1")
    app.include_router(sessions.router, prefix="/api/v1")
    app.include_router(takeover.auth_router, prefix="/api/v1")
    app.include_router(takeover.public_router, prefix="/api/v1")

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "version": __version__}

    @app.get("/metrics")
    async def metrics():
        return PlainTextResponse(ctx.metrics.render(), media_type="text/plain; version=0.0.4")

    _install_errors(app)
    return app


async def _background(ctx) -> None:
    while True:
        try:
            await ctx.manager.reap_idle()
            await ctx.health.check_running()
            ctx.takeover.apply_timeouts()
        except Exception:
            log.exception("background loop failed")
        await asyncio.sleep(ctx.config.devices.reaper_interval_s)


def _install_errors(app: FastAPI) -> None:
    mapping = {
        NotFoundError: 404,
        ConflictError: 409,
        InvalidTransition: 409,
        SignatureMismatchError: 400,
        BootTimeoutError: 504,
        PolicyViolation: 400,
        BudgetExceeded: 402,
        ResidencyError: 400,
        TokenError: 401,
        AdbError: 502,
    }

    @app.exception_handler(SlashError)
    async def handle(request: Request, exc: SlashError):
        status = 400
        for cls, code in mapping.items():
            if isinstance(exc, cls):
                status = code
                break
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    # Touch the enum so a missing import fails at startup rather than at cancel time.
    _ = TaskStatus.NEED_HUMAN
