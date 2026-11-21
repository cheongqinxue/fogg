"""Tool configuration readiness endpoint for the frontend."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, SecretStr

from master.tools import get_user_tool_configuration
from api.auth import authenticated_uid
from utils.kms import KMSConfigurationError, KMSOperationError
from utils.settings import AppSettings, get_settings
from utils.user_tool_config import (
    save_provider_credentials,
    set_tool_active,
)

router = APIRouter(tags=["tools"])

_PROVIDER_LABELS = {
    "google_maps": "Google Maps API key",
    "tavily": "Tavily API key",
    "exa": "Exa API key",
    "firecrawl": "Firecrawl API key",
}
CredentialProvider = Literal["google_maps", "tavily", "exa", "firecrawl"]


class CredentialStatus(BaseModel):
    provider: CredentialProvider
    label: str
    configured: bool


class ToolStatus(BaseModel):
    name: str
    description: str
    active: bool
    status: Literal["ready", "needs_configuration"]
    message: str | None = None
    credentials: list[CredentialStatus] = Field(default_factory=list)


class ToolStatusResponse(BaseModel):
    api_server: Literal["ready"] = "ready"
    tools: list[ToolStatus]


class CredentialUpdateRequest(BaseModel):
    credentials: dict[CredentialProvider, SecretStr] = Field(
        min_length=1,
        description="Provider API keys to encrypt and save for the authenticated user.",
    )


class CredentialUpdateResponse(BaseModel):
    updated: list[CredentialProvider]


class ToolActiveRequest(BaseModel):
    active: bool = Field(description="Whether this tool should be available to the agent.")


class ToolActiveResponse(BaseModel):
    name: str
    active: bool


async def build_tool_status(uid: str, settings: AppSettings | None = None) -> ToolStatusResponse:
    """Describe registered tools and per-user credential/activation state."""
    settings = settings or get_settings()
    configurations = await get_user_tool_configuration(uid, settings=settings)
    statuses: list[ToolStatus] = []
    for config in configurations:
        providers = config["providers"]
        configured = config["configured_providers"]
        missing = [provider for provider in providers if provider not in configured]
        message = None
        if missing and providers == ("google_maps",):
            message = "Add a Google Maps API key to use this tool."
        elif missing and providers and not configured:
            message = "Add an API key for Tavily, Exa, or Firecrawl to use this tool."
        statuses.append(
            ToolStatus(
                name=config["name"],
                description=config["description"],
                active=config["active"],
                status="ready" if config["ready"] else "needs_configuration",
                message=message,
                credentials=[
                    CredentialStatus(
                        provider=provider,
                        label=_PROVIDER_LABELS[provider],
                        configured=provider in configured,
                    )
                    for provider in providers
                ],
            )
        )
    return ToolStatusResponse(tools=statuses)


@router.get("/tools/status", response_model=ToolStatusResponse)
async def get_tool_status(uid: str = Depends(authenticated_uid)) -> ToolStatusResponse:
    """Return readiness and active state for the authenticated user's tools."""
    return await build_tool_status(uid)


@router.put("/tools/credentials", response_model=CredentialUpdateResponse)
async def update_tool_credentials(
    request: CredentialUpdateRequest,
    uid: str = Depends(authenticated_uid),
) -> CredentialUpdateResponse:
    """Encrypt and idempotently replace credentials for the authenticated user."""
    try:
        credentials = {
            provider: secret.get_secret_value().strip()
            for provider, secret in request.credentials.items()
        }
        if any(not api_key for api_key in credentials.values()):
            raise HTTPException(status_code=422, detail="API keys cannot be empty")
        await save_provider_credentials(uid, credentials)
    except (KMSConfigurationError, KMSOperationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Encrypted credential storage is not configured",
        ) from exc
    return CredentialUpdateResponse(updated=list(request.credentials))


@router.put("/tools/{tool_name}/active", response_model=ToolActiveResponse)
async def update_tool_active_state(
    tool_name: str,
    request: ToolActiveRequest,
    uid: str = Depends(authenticated_uid),
) -> ToolActiveResponse:
    """Persist activation state; key-backed tools cannot be enabled while unconfigured."""
    status_response = await build_tool_status(uid)
    tool_status = next((item for item in status_response.tools if item.name == tool_name), None)
    if tool_status is None:
        raise HTTPException(status_code=404, detail="Unknown tool")
    if request.active and tool_status.status != "ready":
        raise HTTPException(
            status_code=409,
            detail="Configure the required provider credential before enabling this tool",
        )
    await set_tool_active(uid, tool_name, request.active)
    return ToolActiveResponse(name=tool_name, active=request.active)
