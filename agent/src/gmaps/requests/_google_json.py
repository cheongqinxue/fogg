"""Shared JSON helpers for Google Maps request bodies."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class GoogleJsonModel(BaseModel):
    """Strict model with camelCase JSON aliases for Google APIs."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        alias_generator=to_camel,
    )


class LatLng(BaseModel):
    """WGS84 point."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
