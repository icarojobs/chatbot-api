from collections.abc import Awaitable, Callable
from http import HTTPStatus

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

ReadinessCheck = Callable[[], Awaitable[bool]]

router = APIRouter(tags=["Saúde"])


class StatusResponse(BaseModel):
    status: str


@router.get("/health", summary="Verifica se o processo está vivo")
async def health() -> StatusResponse:
    return StatusResponse(status="ok")


@router.get(
    "/ready",
    summary="Verifica se a aplicação está pronta para receber tráfego",
    responses={HTTPStatus.SERVICE_UNAVAILABLE: {"model": StatusResponse}},
)
async def ready(request: Request) -> JSONResponse:
    checks: list[ReadinessCheck] = request.app.state.readiness_checks
    results = [await check() for check in checks]
    if all(results):
        return JSONResponse({"status": "ready"})
    return JSONResponse({"status": "not_ready"}, status_code=HTTPStatus.SERVICE_UNAVAILABLE)
