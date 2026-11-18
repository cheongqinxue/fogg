"""Declarative fixtures for all development simulations."""

import re

SKI_RESORTS = [
    {
        "id": "sim-nagano-ski-1",
        "displayName": {"text": "Nagano Mountain Ski Area"},
        "formattedAddress": "Nagano, Japan",
        "location": {"latitude": 36.70, "longitude": 138.17},
    },
    {
        "id": "sim-nagano-ski-2",
        "displayName": {"text": "Nagano Snow Park"},
        "formattedAddress": "Nagano, Japan",
        "location": {"latitude": 36.62, "longitude": 138.20},
    },
]
TEXT_SEARCH_SKI_RESORTS = [
    *SKI_RESORTS,
    {
        "id": "sim-nagano-ski-3",
        "displayName": {"text": "Hakuba Alpine Ski Park"},
        "formattedAddress": "Hakuba, Nagano, Japan",
        "location": {"latitude": 36.698, "longitude": 137.839},
    },
]

# Shinshu Matsumoto Airport (MMJ). Route geometry, distances, and durations
# below are fictional fixtures, not navigable routes or estimates.
AIRPORT = {"latitude": 36.16667, "longitude": 137.92278, "distance": 3}
AIRPORT_PLACE = {
    "id": "sim-matsumoto-airport",
    "displayName": {"text": "Matsumoto Airport"},
    "formattedAddress": "Matsumoto, Nagano, Japan",
    "location": {"latitude": AIRPORT["latitude"], "longitude": AIRPORT["longitude"]},
    "primaryType": "airport",
}
AIRPORT_WAYPOINT = {
    "any_of": [
        {
            "address": re.compile(
                r"(?:matsumoto|nagano|shinshu|mmj).*airport|airport.*(?:matsumoto|nagano|shinshu|mmj)",
                re.I,
            )
        },
        {"place_id": AIRPORT_PLACE["id"]},
        {"center_within_km": AIRPORT},
    ]
}
_ROUTE_FIXTURES = (
    (TEXT_SEARCH_SKI_RESORTS[0], 82000, "5400s", "uxv{Ek`yhYidgBcho@"),
    (TEXT_SEARCH_SKI_RESORTS[1], 76000, "5100s", "uxv{Ek`yhYipwAscu@"),
    (TEXT_SEARCH_SKI_RESORTS[2], 78000, "5700s", "uxv{Ek`yhYywfBrjO"),
)


def _route_case(place, distance, duration, polyline):
    center = {**place["location"], "distance": 1}
    start = {"latLng": {"latitude": AIRPORT["latitude"], "longitude": AIRPORT["longitude"]}}
    end = {"latLng": dict(place["location"])}
    geometry = {"encodedPolyline": polyline}
    step = {
        "distanceMeters": distance,
        "staticDuration": duration,
        "polyline": geometry,
        "startLocation": start,
        "endLocation": end,
        "navigationInstruction": {"instructions": "Simulated route; not for navigation."},
        "travelMode": "DRIVE",
    }
    leg = {
        "distanceMeters": distance,
        "duration": duration,
        "staticDuration": duration,
        "polyline": geometry,
        "startLocation": start,
        "endLocation": end,
        "steps": [step],
    }
    return {
        "expected": {
            "origin": AIRPORT_WAYPOINT,
            "destination": {
                "any_of": [
                    {"place_id": place["id"]},
                    {"address": re.compile(re.escape(place["displayName"]["text"]), re.I)},
                    {"center_within_km": center},
                ]
            },
            "travel_mode": "DRIVE",
            "intermediates": [],
            "compute_alternative_routes": False,
            "optimize_waypoint_order": False,
        },
        "response": {
            "routes": [
                {
                    "distanceMeters": distance,
                    "duration": duration,
                    "staticDuration": duration,
                    "polyline": geometry,
                    "legs": [leg],
                }
            ]
        },
    }


SCENARIOS = {
    "nagano_ski_resorts": {
        "places_text_search": [
            {
                "expected": {
                    "text_query": re.compile(
                        r"(?:matsumoto|nagano|shinshu|mmj).*airport|airport.*(?:matsumoto|nagano|shinshu|mmj)",
                        re.I,
                    )
                },
                "response": {"places": [AIRPORT_PLACE]},
            },
            {
                "expected": {
                    "text_query": re.compile(r"(?=.*ski)(?=.*nagano)", re.I),
                    "area": None,
                },
                "response": {"places": TEXT_SEARCH_SKI_RESORTS},
            },
            {
                "expected": {
                    "text_query": re.compile(r"ski", re.I),
                    "area": {
                        "center_within_km": {
                            "latitude": 36.6513,
                            "longitude": 138.1810,
                            "distance": 100,
                        }
                    },
                },
                "response": {"places": TEXT_SEARCH_SKI_RESORTS},
            },
        ],
        "places_search_nearby": [
            {
                "expected": {
                    "included_types": {"any_regex": re.compile("ski", re.I)},
                    "center_within_km": {
                        "latitude": 36.6513,
                        "longitude": 138.1810,
                        "distance": 100,
                    },
                },
                "response": {"places": TEXT_SEARCH_SKI_RESORTS},
            },
        ],
        "routes_compute": [_route_case(*fixture) for fixture in _ROUTE_FIXTURES],
    },
}
