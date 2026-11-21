"""Read saved itinerary summaries for an account."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from backend.database import get_pool


class ItinerarySummary(BaseModel):
    itinerary_version_id: UUID
    name: str | None
    status: Literal["valid", "broken", "superseded"]


class TripItineraries(BaseModel):
    trip_id: UUID
    name: str
    starts_on: date | None
    ends_on: date | None
    head_itinerary_version_id: UUID | None
    itineraries: list[ItinerarySummary]


class SavedItineraries(BaseModel):
    trips: list[TripItineraries]


async def list_saved_itineraries(account_id: str) -> SavedItineraries:
    """Return trips with saved versions, with the selected version first."""
    async with get_pool().connection() as conn:
        cursor = await conn.execute(
            """
            SELECT t.trip_id, t.name, t.starts_on, t.ends_on, t.head_itinerary_version_id,
                   v.itinerary_version_id, v.name AS itinerary_name, v.status
            FROM trips AS t
            JOIN itinerary_versions AS v ON v.trip_id = t.trip_id
            WHERE t.account_id = %s
            ORDER BY t.updated_at DESC, t.trip_id,
                     (v.itinerary_version_id = t.head_itinerary_version_id) DESC NULLS LAST,
                     v.version_number DESC
            """,
            (account_id,),
        )
        rows = await cursor.fetchall()

    trips: dict[UUID, TripItineraries] = {}
    for row in rows:
        trip_id = row["trip_id"]
        if trip_id not in trips:
            trips[trip_id] = TripItineraries(
                trip_id=trip_id,
                name=row["name"],
                starts_on=row["starts_on"],
                ends_on=row["ends_on"],
                head_itinerary_version_id=row["head_itinerary_version_id"],
                itineraries=[],
            )
        trips[trip_id].itineraries.append(
            ItinerarySummary(
                itinerary_version_id=row["itinerary_version_id"],
                name=row["itinerary_name"],
                status=row["status"],
            )
        )
    return SavedItineraries(trips=list(trips.values()))
