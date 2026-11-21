"""Version 1 HTTP API (health + user-scoped routes)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from api.routes.account_auth import router as account_auth_router
from api.routes.tool_status import router as tool_status_router
from api.routes.users import router as users_router

router = APIRouter(prefix="/v1", tags=["v1"])
router.include_router(account_auth_router)
router.include_router(users_router)
router.include_router(tool_status_router)


class HealthResponse(BaseModel):
    """Liveness response."""

    status: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe."""
    return HealthResponse(status="ok")
