"""FastAPI application factory for the operational HTTP skeleton."""

from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

import structlog
from fastapi import FastAPI

from app.core.logging import setup_logging
from app.core.messaging import MessagingSettings
from app.core.settings import get_settings
from app.entrypoints.http.errors import install_errors
from app.entrypoints.http.middlewares import RequestIdMiddleware
from app.entrypoints.http.routers.dialogues import router as dialogues_router
from app.entrypoints.http.routers.health import router as health_router
from app.infrastructure.bootstrap.messaging import MessagingRuntime, messaging_runtime

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    async with AsyncExitStack() as stack:
        settings = MessagingSettings()
        if app.state.messaging_runtime is None and settings.enabled:
            app.state.messaging_runtime = await stack.enter_async_context(
                messaging_runtime(settings)
            )
        if app.state.messaging_runtime is not None:
            await app.state.messaging_runtime.validate_schema()
        app.state.ready = True
        logger.info("application started", version=app.version)
        try:
            yield
        finally:
            app.state.ready = False
            logger.info("application shutting down")


def create_app(*, runtime: MessagingRuntime | None = None) -> FastAPI:
    settings = get_settings()
    setup_logging(settings)

    app = FastAPI(
        title="Andruha Messenger / Messages and Dialogues Service",
        version=settings.APP_VERSION,
        lifespan=lifespan,
    )
    app.state.ready = False
    app.state.messaging_runtime = runtime
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health_router)
    app.include_router(dialogues_router)
    install_errors(app)
    return app
