"""Code-owned response fields for route planning tools."""

ROUTE_MASK = ",".join(
    (
        "routes.routeLabels",
        "routes.distanceMeters",
        "routes.duration",
        "routes.staticDuration",
        "routes.polyline.encodedPolyline",
        "routes.description",
        "routes.warnings",
        "routes.viewport",
        "routes.localizedValues",
        "routes.travelAdvisory.transitFare",
        "routes.legs.distanceMeters",
        "routes.legs.duration",
        "routes.legs.staticDuration",
        "routes.legs.polyline.encodedPolyline",
        "routes.legs.startLocation",
        "routes.legs.endLocation",
        "routes.legs.localizedValues",
        "routes.legs.stepsOverview",
        "routes.legs.steps.distanceMeters",
        "routes.legs.steps.staticDuration",
        "routes.legs.steps.polyline.encodedPolyline",
        "routes.legs.steps.startLocation",
        "routes.legs.steps.endLocation",
        "routes.legs.steps.navigationInstruction",
        "routes.legs.steps.localizedValues",
        "routes.legs.steps.transitDetails",
        "routes.legs.steps.travelMode",
        "fallbackInfo",
        "geocodingResults",
    )
)
ROUTE_OPTIMIZED_ORDER_FIELD = "routes.optimizedIntermediateWaypointIndex"
MATRIX_MASK = "originIndex,destinationIndex,status,condition,distanceMeters,duration"
