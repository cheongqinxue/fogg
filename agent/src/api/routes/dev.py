"""Development-only maintenance routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.dev_reset import (
    DevResetRequest,
    DevResetResponse,
    dev_reset_enabled,
    reset_agent_state,
)

router = APIRouter(prefix="/v1/dev", tags=["dev"])


@router.post("/reset", response_model=DevResetResponse)
async def post_dev_reset(body: DevResetRequest) -> DevResetResponse:
    """Clear LangGraph checkpoints and layout rows (local testing)."""
    if not dev_reset_enabled():
        raise HTTPException(status_code=403, detail="AGENT_DEV_RESET_ENABLED is not set")
    try:
        return await reset_agent_state(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
