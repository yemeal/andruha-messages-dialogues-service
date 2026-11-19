"""Process liveness and application-readiness routes."""

from fastapi import APIRouter, Request, Response, status

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(
    request: Request,
    response: Response,
) -> dict[str, str]:
    is_ready = bool(getattr(request.app.state, "ready", False))
    runtime = getattr(request.app.state, "messaging_runtime", None)
    if is_ready and runtime is not None:
        is_ready = await runtime.ready()
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": "ready" if is_ready else "unavailable"}
