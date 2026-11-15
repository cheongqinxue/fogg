"""Async tools and Pydantic input schemas for the travel agent."""

from __future__ import annotations

import json
import math
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_utils.request_context import request_user_id
from gmaps.requests import (
    PlacesGetRequest,
    PlacesSearchNearbyRequest,
    PlacesTextSearchRequest,
    RoutesComputeRouteMatrixRequest,
    RoutesComputeRoutesRequest,
)
from gmaps.requests.places import (
    Circle,
    LocationRestriction,
    Rectangle,
    TextSearchBias,
    TextSearchRestriction,
)
from gmaps.requests.search_fields import (
    NEARBY_SEARCH_PRO_MASK,
    PLACE_DETAILS_PRO_MASK,
    TEXT_SEARCH_PRO_MASK,
)
from gmaps.requests.route_fields import MATRIX_MASK, ROUTE_MASK, ROUTE_OPTIMIZED_ORDER_FIELD
from gmaps.requests.routes import RouteMatrixWaypoint, Waypoint
from layout._tool import execute_map_set_viewport_tool


class ToolInput(BaseModel):
    """Strict base for tool arguments; reject unknown model-generated fields."""

    model_config = ConfigDict(extra="forbid")


class EchoDestinationInput(ToolInput):
    name: str = Field(description="Destination label used only to verify the tool loop is working.")


class TextSearchArea(ToolInput):
    latitude: float = Field(ge=-90, le=90, description="Center latitude in WGS84 degrees.")
    longitude: float = Field(ge=-180, le=180, description="Center longitude in WGS84 degrees.")
    radius_meters: float = Field(gt=0, le=50000, description="Radius in meters, up to 50,000.")
    mode: Literal["bias", "restrict"] = Field(
        description="bias favors this area; restrict excludes results outside the radius."
    )


class PlacesTextSearchInput(ToolInput):
    text_query: str = Field(description="Natural-language search, e.g. 'quiet cafes in Kyoto'.")
    language_code: str | None = Field(
        default=None, description="Preferred response language as a BCP-47 code, e.g. 'en'."
    )
    region_code: str | None = Field(
        default=None, description="Two-letter region bias, e.g. 'JP'; this is not a hard filter."
    )
    included_type: str | None = Field(
        default=None, description="Optional single Google place type to restrict results to."
    )
    open_now: bool | None = Field(
        default=None, description="If true, return places currently open; if false, closed places."
    )
    min_rating: float | None = Field(
        default=None, ge=0, le=5, description="Minimum Google rating from 0 to 5."
    )
    page_token: str | None = Field(
        default=None, description="Next-page token returned by a previous text search."
    )
    area: TextSearchArea | None = Field(
        default=None,
        description="Optional center and radius: bias toward it or strictly restrict results to it.",
    )


class PlacesNearbyInput(ToolInput):
    latitude: float = Field(ge=-90, le=90, description="Circle center latitude in WGS84 degrees.")
    longitude: float = Field(
        ge=-180, le=180, description="Circle center longitude in WGS84 degrees."
    )
    radius_meters: float = Field(gt=0, description="Search radius around the center, in meters.")
    included_types: list[str] = Field(
        min_length=1,
        description="Google place types to include, e.g. ['restaurant', 'cafe']; at least one.",
    )
    max_result_count: int = Field(
        default=10, ge=1, le=20, description="Maximum places to return (1–20; default 10)."
    )
    rank_preference: Literal["DISTANCE", "POPULARITY"] | None = Field(
        default=None,
        description="Order by 'DISTANCE' from the center or 'POPULARITY'; omit for Google's default.",
    )
    language_code: str | None = Field(
        default=None, description="Preferred response language as a BCP-47 code, e.g. 'en'."
    )


class PlacesAutocompleteInput(ToolInput):
    input: str = Field(description="Partial place name or address typed by the user.")
    language_code: str | None = Field(
        default=None, description="Preferred suggestion language as a BCP-47 code, e.g. 'en'."
    )
    region_code: str | None = Field(default=None, description="Two-letter region bias, e.g. 'SG'.")
    session_token: str | None = Field(
        default=None,
        description="Token shared by autocomplete and place selection in one UI session.",
    )


class PlacesGetInput(ToolInput):
    place_id: str = Field(description="Google Place ID from a previous Places result.")


class WaypointInput(ToolInput):
    address: str | None = Field(
        default=None, description="Human-readable address for the waypoint."
    )
    place_id: str | None = Field(default=None, description="Google Place ID for the waypoint.")
    latitude: float | None = Field(
        default=None, ge=-90, le=90, description="WGS84 latitude; provide with longitude."
    )
    longitude: float | None = Field(
        default=None, ge=-180, le=180, description="WGS84 longitude; provide with latitude."
    )

    @model_validator(mode="after")
    def validate_location(self) -> WaypointInput:
        has_coordinates = self.latitude is not None or self.longitude is not None
        complete_coordinates = self.latitude is not None and self.longitude is not None
        choices = (
            int(self.address is not None)
            + int(self.place_id is not None)
            + int(complete_coordinates)
        )
        if choices != 1 or (has_coordinates and not complete_coordinates):
            raise ValueError("Provide exactly one of address, place_id, or latitude plus longitude")
        return self

    def to_waypoint(self) -> Waypoint:
        if self.address is not None:
            return Waypoint(address=self.address)
        if self.place_id is not None:
            return Waypoint(place_id=self.place_id)
        return Waypoint(
            location={"lat_lng": {"latitude": self.latitude, "longitude": self.longitude}}
        )


class RoutesComputeInput(ToolInput):
    origin: WaypointInput = Field(
        description="Route start as an address, Place ID, or coordinate pair."
    )
    destination: WaypointInput = Field(
        description="Route end as an address, Place ID, or coordinate pair."
    )
    intermediates: list[WaypointInput] = Field(
        default_factory=list, description="Optional ordered stops between origin and destination."
    )
    travel_mode: Literal["DRIVE", "BICYCLE", "WALK", "TWO_WHEELER", "TRANSIT"] = Field(
        default="DRIVE",
        description="Travel mode: DRIVE, BICYCLE, WALK, TWO_WHEELER, or TRANSIT.",
    )
    routing_preference: (
        Literal["TRAFFIC_UNAWARE", "TRAFFIC_AWARE", "TRAFFIC_AWARE_OPTIMAL"] | None
    ) = Field(
        default="TRAFFIC_UNAWARE",
        description="Traffic model: TRAFFIC_UNAWARE is fastest/cheapest; TRAFFIC_AWARE uses current traffic; TRAFFIC_AWARE_OPTIMAL prioritizes traffic-aware quality.",
    )
    compute_alternative_routes: bool = Field(
        default=False,
        description="If true, request alternative routes when available; ignored with intermediate stops.",
    )
    optimize_waypoint_order: bool = Field(
        default=False,
        description="If true, reorder intermediate stops to reduce route length; may increase billing tier.",
    )
    language_code: str = Field(
        default="en-US", description="Language for route instructions, as a BCP-47 code."
    )
    units: Literal["METRIC", "IMPERIAL"] = Field(
        default="METRIC", description="Distance units for display: METRIC or IMPERIAL."
    )


class RoutesMatrixInput(ToolInput):
    origins: list[WaypointInput] = Field(
        min_length=1, description="At least one route starting point."
    )
    destinations: list[WaypointInput] = Field(
        min_length=1, description="At least one route destination."
    )
    travel_mode: Literal["DRIVE", "BICYCLE", "WALK", "TWO_WHEELER", "TRANSIT"] = Field(
        default="DRIVE", description="Travel mode: DRIVE, BICYCLE, WALK, TWO_WHEELER, or TRANSIT."
    )
    routing_preference: (
        Literal["TRAFFIC_UNAWARE", "TRAFFIC_AWARE", "TRAFFIC_AWARE_OPTIMAL"] | None
    ) = Field(
        default=None, description="Optional traffic model; traffic-aware options can cost more."
    )


class MapViewportInput(ToolInput):
    lat: float = Field(ge=-90, le=90, description="Target map center latitude in WGS84 degrees.")
    lng: float = Field(ge=-180, le=180, description="Target map center longitude in WGS84 degrees.")
    zoom: float | None = Field(
        default=None,
        ge=0,
        le=22,
        description="Optional map zoom; omit to preserve current zoom when reasonable.",
    )
    label: str | None = Field(
        default=None, description="Short human-readable label for the new map focus."
    )


def _json_result(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


@tool(args_schema=PlacesTextSearchInput)
async def places_text_search(
    text_query: str,
    language_code: str | None = None,
    region_code: str | None = None,
    included_type: str | None = None,
    open_now: bool | None = None,
    min_rating: float | None = None,
    page_token: str | None = None,
    area: dict[str, Any] | None = None,
) -> str:
    """Search Places by natural-language query and return matching candidates."""
    search_area = TextSearchArea.model_validate(area) if area is not None else None
    bias = None
    restriction = None
    if search_area is not None:
        if search_area.mode == "bias":
            bias = TextSearchBias(
                circle=Circle(
                    center={"latitude": search_area.latitude, "longitude": search_area.longitude},
                    radius=search_area.radius_meters,
                )
            )
        else:
            angular = search_area.radius_meters / 6371008.8
            lat = math.radians(search_area.latitude)
            south, north = max(-math.pi / 2, lat - angular), min(math.pi / 2, lat + angular)
            delta_lon = (
                math.pi
                if south <= -math.pi / 2 or north >= math.pi / 2
                else math.asin(min(1, math.sin(angular) / math.cos(lat)))
            )
            west = ((search_area.longitude - math.degrees(delta_lon) + 180) % 360) - 180
            east = ((search_area.longitude + math.degrees(delta_lon) + 180) % 360) - 180
            if delta_lon == math.pi:
                west, east = -180, 180
            restriction = TextSearchRestriction(
                rectangle=Rectangle(
                    low={"latitude": math.degrees(south), "longitude": west},
                    high={"latitude": math.degrees(north), "longitude": east},
                )
            )
    req = PlacesTextSearchRequest(
        text_query=text_query,
        field_mask=TEXT_SEARCH_PRO_MASK,
        page_size=10,
        language_code=language_code,
        region_code=region_code,
        included_type=included_type,
        open_now=open_now,
        min_rating=min_rating,
        page_token=page_token,
        location_bias=bias,
        location_restriction=restriction,
    )
    result = await req.call()
    if search_area is not None and search_area.mode == "restrict":
        kept = []
        indices = []
        for index, place in enumerate(result.get("places", [])):
            point = place.get("location")
            if not isinstance(point, dict) or "latitude" not in point or "longitude" not in point:
                continue
            lat1, lat2 = math.radians(search_area.latitude), math.radians(point["latitude"])
            dlat = lat2 - lat1
            dlng = math.radians(point["longitude"] - search_area.longitude)
            a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
            if 2 * 6371008.8 * math.asin(math.sqrt(min(1, a))) <= search_area.radius_meters:
                kept.append(place)
                indices.append(index)
        result = dict(result, places=kept)
        if isinstance(result.get("contextualContents"), list):
            result["contextualContents"] = [
                result["contextualContents"][i]
                for i in indices
                if i < len(result["contextualContents"])
            ]
    return _json_result(result)


@tool(args_schema=PlacesNearbyInput)
async def places_search_nearby(
    latitude: float,
    longitude: float,
    radius_meters: float,
    included_types: list[str],
    max_result_count: int = 10,
    rank_preference: Literal["DISTANCE", "POPULARITY"] | None = None,
    language_code: str | None = None,
) -> str:
    """Find places of selected types inside a radius around a coordinate."""
    req = PlacesSearchNearbyRequest(
        field_mask=NEARBY_SEARCH_PRO_MASK,
        location_restriction=LocationRestriction(
            circle=Circle(
                center={"latitude": latitude, "longitude": longitude}, radius=radius_meters
            )
        ),
        included_types=included_types,
        max_result_count=max_result_count,
        rank_preference=rank_preference,
        language_code=language_code,
    )
    return _json_result(await req.call())


@tool(args_schema=PlacesGetInput)
async def places_get(place_id: str) -> str:
    """Fetch requested details for a Google Place ID."""
    return _json_result(
        await PlacesGetRequest(place_id=place_id, field_mask=PLACE_DETAILS_PRO_MASK).call()
    )


@tool(args_schema=RoutesComputeInput)
async def routes_compute(
    origin: dict[str, Any],
    destination: dict[str, Any],
    intermediates: list[dict[str, Any]] | None = None,
    travel_mode: Literal["DRIVE", "BICYCLE", "WALK", "TWO_WHEELER", "TRANSIT"] = "DRIVE",
    routing_preference: Literal["TRAFFIC_UNAWARE", "TRAFFIC_AWARE", "TRAFFIC_AWARE_OPTIMAL"]
    | None = "TRAFFIC_UNAWARE",
    compute_alternative_routes: bool = False,
    optimize_waypoint_order: bool = False,
    language_code: str = "en-US",
    units: Literal["METRIC", "IMPERIAL"] = "METRIC",
) -> str:
    """Compute a route between endpoints, optionally visiting intermediate stops."""
    req = RoutesComputeRoutesRequest(
        field_mask=f"{ROUTE_MASK},{ROUTE_OPTIMIZED_ORDER_FIELD}"
        if optimize_waypoint_order
        else ROUTE_MASK,
        origin=WaypointInput.model_validate(origin).to_waypoint(),
        destination=WaypointInput.model_validate(destination).to_waypoint(),
        intermediates=[
            WaypointInput.model_validate(item).to_waypoint() for item in intermediates or []
        ],
        travel_mode=travel_mode,
        routing_preference=routing_preference,
        compute_alternative_routes=compute_alternative_routes,
        optimize_waypoint_order=optimize_waypoint_order,
        language_code=language_code,
        units=units,
    )
    return _json_result(await req.call())


@tool(args_schema=RoutesMatrixInput)
async def routes_compute_matrix(
    origins: list[dict[str, Any]],
    destinations: list[dict[str, Any]],
    travel_mode: Literal["DRIVE", "BICYCLE", "WALK", "TWO_WHEELER", "TRANSIT"] = "DRIVE",
    routing_preference: Literal["TRAFFIC_UNAWARE", "TRAFFIC_AWARE", "TRAFFIC_AWARE_OPTIMAL"]
    | None = None,
) -> str:
    """Compare travel routes for every origin and destination pair."""
    req = RoutesComputeRouteMatrixRequest(
        field_mask=MATRIX_MASK,
        origins=[
            RouteMatrixWaypoint(waypoint=WaypointInput.model_validate(item).to_waypoint())
            for item in origins
        ],
        destinations=[
            RouteMatrixWaypoint(waypoint=WaypointInput.model_validate(item).to_waypoint())
            for item in destinations
        ],
        travel_mode=travel_mode,
        routing_preference=routing_preference,
    )
    return _json_result(await req.call())


@tool(args_schema=MapViewportInput)
async def map_set_viewport(
    lat: float, lng: float, zoom: float | None = None, label: str | None = None
) -> str:
    """Move the client map to a useful center and optional zoom."""
    return await execute_map_set_viewport_tool(
        request_user_id.get(), lat=lat, lng=lng, zoom=zoom, label=label
    )


@tool(args_schema=EchoDestinationInput)
def echo_destination(name: str) -> str:
    """Connectivity test only; this does not search for or save a destination."""
    return f"Noted destination: {name.strip()}"


def get_tools():
    """Return async tools registered with the model and ToolNode."""
    return [
        places_text_search,
        places_search_nearby,
        places_get,
        routes_compute,
        routes_compute_matrix,
        map_set_viewport,
        echo_destination,
    ]
