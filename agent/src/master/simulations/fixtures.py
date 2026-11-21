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
    "web_research": {
        "web_search": [
            {
                "expected": {
                    "query": re.compile(
                        r"(?=.*(?:s\s*&\s*p|s&p|s\s+p))(?=.*500)(?=.*(?:week|weekly|gain|loss|change))",
                        re.I,
                    )
                },
                "response": {
                    "provider": "simulation",
                    "results": [
                        {
                            "title": "S&P 500 weekly performance (simulated)",
                            "url": "https://example.com/simulated/sp500-weekly",
                            "snippet": (
                                "SIMULATED TEST DATA: For this scenario, the S&P 500 closed at "
                                "6,602.37 on 2026-11-20, down 0.42% from 2026-11-13. "
                                "This fixture is not a live market quote."
                            ),
                        },
                        {
                            "title": "S&P 500 index history (simulated)",
                            "url": "https://example.com/simulated/sp500-history",
                            "snippet": (
                                "SIMULATED TEST DATA: Compare the Friday closes for the "
                                "requested one-week period; the index fell by 27.92 points."
                            ),
                        },
                    ],
                },
            },
            {
                "expected": {
                    "query": re.compile(
                        r"(?=.*busan)(?=.*(?:local|locals|resident|residents))(?=.*(?:supper|dinner|eat|food))",
                        re.I,
                    )
                },
                "response": {
                    "provider": "simulation",
                    "results": [
                        {
                            "title": "Late-night pork and rice soup in Seomyeon (simulated)",
                            "url": "https://example.com/simulated/busan-seomyeon-gukbap",
                            "snippet": (
                                "SIMULATED TEST DATA: Seomyeon has 24-hour dwaeji-gukbap "
                                "restaurants that are popular after work and late-night meals."
                            ),
                        },
                        {
                            "title": "Busan's Jagalchi seafood supper spots (simulated)",
                            "url": "https://example.com/simulated/busan-jagalchi-seafood",
                            "snippet": (
                                "SIMULATED TEST DATA: Jagalchi and nearby Nampo-dong are known "
                                "for casual seafood restaurants serving evening meals."
                            ),
                        },
                        {
                            "title": "Dongnae pajeon and local evening dining (simulated)",
                            "url": "https://example.com/simulated/busan-dongnae-pajeon",
                            "snippet": (
                                "SIMULATED TEST DATA: Dongnae is associated with pajeon and "
                                "makgeolli restaurants for a relaxed supper."
                            ),
                        },
                    ],
                },
            },
        ],
        "web_extract": [
            {
                "expected": {"url": re.compile(r"example\.com/simulated/sp500-weekly")},
                "response": {
                    "provider": "simulation",
                    "url": "https://example.com/simulated/sp500-weekly",
                    "content": (
                        "# S&P 500 weekly performance (simulated)\n\n"
                        "SIMULATED TEST DATA: The scenario's Friday close is 6,602.37 on "
                        "2026-11-20. The prior Friday close is 6,630.29 on 2026-11-13, "
                        "a decline of 27.92 points (0.42%). This is not live market data."
                    ),
                },
            },
            {
                "expected": {
                    "url": re.compile(r"example\.com/simulated/busan-(?:seomyeon|jagalchi|dongnae)")
                },
                "response": {
                    "provider": "simulation",
                    "url": "https://example.com/simulated/busan-local-supper",
                    "content": (
                        "# Busan supper options (simulated)\n\n"
                        "SIMULATED TEST DATA: Seomyeon is represented by late-night "
                        "dwaeji-gukbap restaurants; Jagalchi and Nampo-dong by casual seafood; "
                        "and Dongnae by pajeon restaurants. These are fixture examples, "
                        "not verified current recommendations."
                    ),
                },
            },
        ],
    },
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
