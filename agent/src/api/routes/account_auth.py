"""Local onboarding and password session HTTP routes."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Annotated, Literal

from backend.accounts import EmailAlreadyRegistered, login_account, register_account, revoke_session
from backend.profiles import BioDetails, ImmigrationDetails
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, SecretStr, StringConstraints, field_validator
from utils.identity import (
    IdentityConfigurationError,
    IdentityProviderUnavailable,
    exchange_google_token,
    google_sign_in_enabled,
    password_sign_in_enabled,
    session_endpoints_enabled,
)

from api.auth import authenticated_account_id, parse_bearer_token

CountryCode = Annotated[
    str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Za-z]{2}$")
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Address = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_lower=True, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
    ),
]


class PasswordLogin(BaseModel):
    email: Email
    password: SecretStr = Field(min_length=1, max_length=256)


class GoogleSignIn(BaseModel):
    id_token: SecretStr = Field(min_length=1, max_length=8192)


class ImmigrationEntry(BaseModel):
    country_code: CountryCode
    kind: Literal["citizenship", "permanent_resident"]


class AccountRegistration(PasswordLogin):
    password: SecretStr = Field(min_length=15, max_length=256)
    name: Name
    home_formatted_address: Address
    home_country_code: CountryCode
    gender: Name | None = None
    immigration_statuses: list[ImmigrationEntry] = Field(default_factory=list, max_length=50)

    @field_validator("immigration_statuses")
    @classmethod
    def unique_statuses(cls, entries: list[ImmigrationEntry]) -> list[ImmigrationEntry]:
        if len({(entry.country_code, entry.kind) for entry in entries}) != len(entries):
            raise ValueError("Each country and status combination must be unique")
        return entries


class SessionIdentity(BaseModel):
    account_id: str


class SessionResponse(SessionIdentity):
    access_token: str
    expires_at: datetime


class _AuthRoute(APIRoute):
    """Keep passwords and profile fields out of validation error responses."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[None, None, Response]]:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError as exc:
                raise HTTPException(422, "Check your account details and try again.") from exc

        return handle


async def _require_password_sign_in() -> None:
    if not password_sign_in_enabled():
        raise HTTPException(404, "Password sign-in is unavailable.")


async def _require_google_sign_in() -> None:
    if not google_sign_in_enabled():
        raise HTTPException(404, "Google sign-in is unavailable.")


async def _require_session_endpoints() -> None:
    if not session_endpoints_enabled():
        raise HTTPException(404, "Session endpoints are unavailable.")


router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    route_class=_AuthRoute,
)


@router.post(
    "/register",
    response_model=SessionResponse,
    status_code=201,
    dependencies=[Depends(_require_password_sign_in)],
)
async def register(body: AccountRegistration, response: Response) -> SessionResponse:
    bio = BioDetails(
        name=body.name,
        gender=body.gender,
        home_formatted_address=body.home_formatted_address,
        home_country_code=body.home_country_code,
    )
    entries = [
        ImmigrationDetails.model_validate(entry.model_dump()) for entry in body.immigration_statuses
    ]
    try:
        session = await register_account(body.email, body.password.get_secret_value(), bio, entries)
    except EmailAlreadyRegistered as exc:
        raise HTTPException(409, "An account already exists for that email.") from exc
    response.headers["Cache-Control"] = "no-store"
    return SessionResponse.model_validate(session, from_attributes=True)


@router.post(
    "/login", response_model=SessionResponse, dependencies=[Depends(_require_password_sign_in)]
)
async def login(body: PasswordLogin, response: Response) -> SessionResponse:
    session = await login_account(body.email, body.password.get_secret_value())
    if session is None:
        raise HTTPException(401, "Email or password is incorrect.")
    response.headers["Cache-Control"] = "no-store"
    return SessionResponse.model_validate(session, from_attributes=True)


@router.post(
    "/google", response_model=SessionResponse, dependencies=[Depends(_require_google_sign_in)]
)
async def google_login(body: GoogleSignIn, response: Response) -> SessionResponse:
    """Exchange an Identity Platform token for a FOGG session."""
    try:
        session = await exchange_google_token(body.id_token.get_secret_value().strip())
    except (IdentityConfigurationError, IdentityProviderUnavailable) as exc:
        raise HTTPException(503, "Google sign-in is unavailable.") from exc
    if session is None:
        raise HTTPException(401, "Google identity could not be verified.")
    response.headers["Cache-Control"] = "no-store"
    return SessionResponse.model_validate(session, from_attributes=True)


@router.get(
    "/session", response_model=SessionIdentity, dependencies=[Depends(_require_session_endpoints)]
)
async def read_session(
    response: Response, account_id: str = Depends(authenticated_account_id)
) -> SessionIdentity:
    response.headers["Cache-Control"] = "no-store"
    return SessionIdentity(account_id=account_id)


@router.delete("/session", status_code=204, dependencies=[Depends(_require_session_endpoints)])
async def logout(authorization: str | None = Header(default=None)) -> None:
    token = parse_bearer_token(authorization)
    if token:
        await revoke_session(token)
