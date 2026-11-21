"""Postgres reads and writes for profiles owned by an internal account."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from backend.database import get_pool


class BioDetails(BaseModel):
    name: str | None = None
    gender: str | None = None
    home_formatted_address: str | None = None
    home_country_code: str | None = None


class ImmigrationDetails(BaseModel):
    country_code: str
    kind: Literal["citizenship", "permanent_resident", "visa"]
    valid_from: date | None = None
    valid_until: date | None = None
    label: str | None = None


class ImmigrationStatus(ImmigrationDetails):
    id: UUID


class UserProfile(BaseModel):
    account_id: UUID
    bio: BioDetails = Field(default_factory=BioDetails)
    immigration_statuses: list[ImmigrationStatus] = Field(default_factory=list)
    preference_summary: str | None = None
    trip_summary: str | None = None


async def get_profile(account_id: str) -> UserProfile | None:
    """Read a profile without creating an account as a side effect."""
    async with get_pool().connection() as conn:
        cursor = await conn.execute(
            """
            SELECT u.account_id, b.name, b.gender, b.home_formatted_address,
                   b.home_country_code, s.preference_summary, s.trip_summary
            FROM users u
            LEFT JOIN user_bio_details b ON b.account_id = u.account_id
            LEFT JOIN user_summaries s ON s.account_id = u.account_id
            WHERE u.account_id = %s
            """,
            (account_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        cursor = await conn.execute(
            """
            SELECT id, country_code, kind, valid_from, valid_until, label
            FROM immigration_statuses WHERE account_id = %s
            ORDER BY country_code, kind, id
            """,
            (row["account_id"],),
        )
        return UserProfile(
            account_id=row["account_id"],
            bio=BioDetails.model_validate(row),
            immigration_statuses=[
                ImmigrationStatus.model_validate(status) for status in await cursor.fetchall()
            ],
            preference_summary=row["preference_summary"],
            trip_summary=row["trip_summary"],
        )


async def save_bio_details(account_id: str, bio: BioDetails) -> bool:
    """Replace the basic details for an existing account. Return whether it exists."""
    async with get_pool().connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO user_bio_details (
                account_id, name, gender, home_formatted_address, home_country_code
            )
            SELECT account_id, %s, %s, %s, %s FROM users WHERE account_id = %s
            ON CONFLICT (account_id) DO UPDATE SET
                name = EXCLUDED.name, gender = EXCLUDED.gender,
                home_formatted_address = EXCLUDED.home_formatted_address,
                home_country_code = EXCLUDED.home_country_code, updated_at = now()
            """,
            (bio.name, bio.gender, bio.home_formatted_address, bio.home_country_code, account_id),
        )
        return cursor.rowcount == 1


async def save_immigration_status(
    account_id: str, details: ImmigrationDetails, *, status_id: UUID | None = None
) -> UUID | None:
    """Add a status or replace an existing status owned by this account."""
    fields = (
        details.country_code,
        details.kind,
        details.valid_from,
        details.valid_until,
        details.label,
    )
    async with get_pool().connection() as conn:
        if status_id is None:
            cursor = await conn.execute(
                """
                INSERT INTO immigration_statuses (
                    account_id, country_code, kind, valid_from, valid_until, label
                )
                SELECT account_id, %s, %s, %s, %s, %s FROM users WHERE account_id = %s
                RETURNING id
                """,
                (*fields, account_id),
            )
        else:
            cursor = await conn.execute(
                """
                UPDATE immigration_statuses SET
                    country_code = %s, kind = %s, valid_from = %s, valid_until = %s, label = %s
                WHERE id = %s AND account_id = %s
                RETURNING id
                """,
                (*fields, status_id, account_id),
            )
        row = await cursor.fetchone()
        return row["id"] if row is not None else None
