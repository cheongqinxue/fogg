#!/usr/bin/env python3
"""Download Google Maps API specs and reference pages into docs/google-maps-api/."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docs" / "google-maps-api"))
from free_tier_caps import (  # noqa: E402
    BILLING_MODEL_SUMMARY,
    LEGACY_INFO_TABLE,
    LEGACY_OPERATIONS,
    PLACES_INFO_TABLE,
    PLACES_OPERATIONS,
    apply_extensions_to_operation,
    free_tier_extension,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs" / "google-maps-api"
DISCOVERY_DIR = DOCS_ROOT / "discovery"
REFERENCE_DIR = DOCS_ROOT / "reference" / "html"
OPENAPI_DIR = DOCS_ROOT / "openapi"
TOOLS_DIR = REPO_ROOT / "tools" / "google-maps-api-spec"

PLACES_DISCOVERY_URL = "https://places.googleapis.com/$discovery/rest?version=v1"
ROUTES_DISCOVERY_URL = "https://routes.googleapis.com/$discovery/rest?version=v2"

REFERENCE_PAGES: list[tuple[str, str]] = [
    ("places-rest-index", "https://developers.google.com/maps/documentation/places/web-service/reference/rest"),
    ("places-searchText", "https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places/searchText"),
    ("places-searchNearby", "https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places/searchNearby"),
    ("places-autocomplete", "https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places/autocomplete"),
    ("places-get", "https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places/get"),
    ("places-data-fields", "https://developers.google.com/maps/documentation/places/web-service/data-fields"),
    ("places-usage-billing", "https://developers.google.com/maps/documentation/places/web-service/usage-and-billing"),
    ("routes-rest-index", "https://developers.google.com/maps/documentation/routes/reference/rest"),
    ("routes-computeRoutes", "https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes"),
    ("routes-computeRouteMatrix", "https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRouteMatrix"),
    ("routes-usage-billing", "https://developers.google.com/maps/documentation/routes/usage-and-billing"),
    ("geocoding-request", "https://developers.google.com/maps/documentation/geocoding/requests-geocoding"),
    ("directions-legacy", "https://developers.google.com/maps/documentation/directions/get-directions"),
    ("maps-grounding-lite", "https://developers.google.com/maps/ai/grounding-lite"),
]


def _fetch_url(url: str, api_key: str | None = None) -> bytes:
    """Fetch URL bytes; append API key query param when provided.

    Args:
        url: Target URL.
        api_key: Optional Google Maps API key for discovery endpoints.

    Returns:
        Response body bytes.

    Raises:
        urllib.error.HTTPError: On non-success HTTP status.
    """
    request_url = url
    if api_key and "key=" not in url:
        separator = "&" if "?" in url else "?"
        request_url = f"{url}{separator}key={api_key}"
    request = urllib.request.Request(
        request_url,
        headers={"User-Agent": "fogg-docs-sync/1.0 (+local dev)"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def download_reference_pages() -> None:
    """Save Google developer reference pages as HTML snapshots."""
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}
    for slug, url in REFERENCE_PAGES:
        dest = REFERENCE_DIR / f"{slug}.html"
        try:
            body = _fetch_url(url)
        except urllib.error.HTTPError as exc:
            print(f"WARN: failed {slug}: HTTP {exc.code}", file=sys.stderr)
            continue
        dest.write_bytes(body)
        manifest[slug] = url
        print(f"reference: {slug}.html")
    (REFERENCE_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def download_discovery(api_key: str | None) -> None:
    """Download Places and optional Routes Discovery JSON documents."""
    DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
    places_path = DISCOVERY_DIR / "places-v1-discovery.json"
    places_path.write_bytes(_fetch_url(PLACES_DISCOVERY_URL))
    print(f"discovery: {places_path.relative_to(REPO_ROOT)}")

    routes_path = DISCOVERY_DIR / "routes-v2-discovery.json"
    if not api_key:
        print(
            "SKIP: routes-v2 discovery (set GOOGLE_MAPS_API_KEY to fetch)",
            file=sys.stderr,
        )
        return
    try:
        routes_path.write_bytes(_fetch_url(ROUTES_DISCOVERY_URL, api_key=api_key))
        print(f"discovery: {routes_path.relative_to(REPO_ROOT)}")
    except urllib.error.HTTPError as exc:
        print(f"WARN: routes discovery HTTP {exc.code}", file=sys.stderr)


def _patch_places_openapi(openapi_path: Path) -> None:
    """Add API key header auth, FieldMask, and free-tier metadata to Places OpenAPI."""
    data = json.loads(openapi_path.read_text(encoding="utf-8"))
    components = data.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes["ApiKeyHeader"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-Goog-Api-Key",
    }
    field_mask_param = {
        "name": "X-Goog-FieldMask",
        "in": "header",
        "required": True,
        "description": (
            "Comma-separated fields to return. Controls response shape and billing SKU. "
            "See docs/google-maps-api/reference/html/places-data-fields.html"
        ),
        "schema": {"type": "string"},
        "example": "places.id,places.displayName,places.formattedAddress,places.location",
    }
    for path_item in data.get("paths", {}).values():
        for method in path_item.values():
            if not isinstance(method, dict):
                continue
            params = method.setdefault("parameters", [])
            if not any(p.get("name") == "X-Goog-FieldMask" for p in params):
                params.append(field_mask_param)
            operation_id = method.get("operationId")
            if operation_id and operation_id in PLACES_OPERATIONS:
                apply_extensions_to_operation(method, PLACES_OPERATIONS[operation_id])
    data["security"] = [{"ApiKeyHeader": []}]
    info = data.setdefault("info", {})
    info["description"] = (
        "Generated from Google's Discovery document for Places API (New), "
        "patched with X-Goog-FieldMask and API key auth.\n\n"
        f"{BILLING_MODEL_SUMMARY}\n\n{PLACES_INFO_TABLE}\n\n"
        "Reference HTML snapshots: `docs/google-maps-api/reference/html/`."
    )
    openapi_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _format_extension_yaml_lines(meta: dict) -> str:
    """Format OpenAPI vendor extensions as YAML lines for legacy spec insertion."""
    lines: list[str] = []
    for key, value in free_tier_extension(meta).items():
        if isinstance(value, str):
            escaped = value.replace('"', '\\"')
            lines.append(f'      {key}: "{escaped}"')
        else:
            lines.append(f"      {key}: {value}")
    return "\n".join(lines) + "\n"


def _patch_legacy_openapi_yaml(openapi_path: Path) -> None:
    """Inject free-tier extensions and info table into legacy OpenAPI YAML."""
    text = openapi_path.read_text(encoding="utf-8")
    for op_id, meta in LEGACY_OPERATIONS.items():
        block = _format_extension_yaml_lines(meta)
        text = re.sub(
            rf"(      operationId: {re.escape(op_id)}\n)(?!      x-google-sku:)",
            rf"\1{block}",
            text,
            count=1,
        )
    legacy_info = (
        "API Specification for Google Maps Platform (legacy export).\n\n"
        f"{BILLING_MODEL_SUMMARY}\n\n{LEGACY_INFO_TABLE}"
    )
    text = re.sub(
        r"  description: API Specification for Google Maps Platform\n",
        "  description: |\n    "
        + legacy_info.replace("\n", "\n    ")
        + "\n",
        text,
        count=1,
    )
    openapi_path.write_text(text, encoding="utf-8")


def generate_places_openapi() -> None:
    """Run Node toolchain to convert Places Discovery to OpenAPI 3."""
    discovery_path = DISCOVERY_DIR / "places-v1-discovery.json"
    if not discovery_path.is_file():
        raise FileNotFoundError(f"Missing {discovery_path}; run discovery download first.")

    node_modules = TOOLS_DIR / "node_modules"
    if not node_modules.is_dir():
        subprocess.run(
            ["npm", "install", "--silent"],
            cwd=TOOLS_DIR,
            check=True,
        )

    script = """
const fs = require('fs');
const convert = require('google-discovery-to-swagger');
const s2o = require('swagger2openapi');
const discovery = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
const swagger = convert.convert(discovery);
const outSwagger = process.argv[2];
const outOpenapi = process.argv[3];
fs.writeFileSync(outSwagger, JSON.stringify(swagger, null, 2));
s2o.convert(swagger, { patch: true }, (err, options) => {
  if (err) throw err;
  fs.writeFileSync(outOpenapi, JSON.stringify(options.openapi, null, 2));
  console.log('openapi paths:', Object.keys(options.openapi.paths).length);
});
"""
    swagger2_path = OPENAPI_DIR / "places-v1-swagger2.json"
    openapi3_path = OPENAPI_DIR / "places-v1-openapi3.json"
    subprocess.run(
        ["node", "-e", script, str(discovery_path), str(swagger2_path), str(openapi3_path)],
        cwd=TOOLS_DIR,
        check=True,
    )
    _patch_places_openapi(openapi3_path)
    print(f"openapi: {openapi3_path.relative_to(REPO_ROOT)}")


def main() -> int:
    """Entry point."""
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    for directory in (DISCOVERY_DIR, REFERENCE_DIR, OPENAPI_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    download_reference_pages()
    download_discovery(api_key)
    generate_places_openapi()
    legacy_yaml = OPENAPI_DIR / "google-maps-platform-legacy-openapi3.yml"
    if legacy_yaml.is_file():
        _patch_legacy_openapi_yaml(legacy_yaml)
        print(f"openapi: patched free tier in {legacy_yaml.relative_to(REPO_ROOT)}")
    print("Done. Serve Swagger UI: ./scripts/serve_google_maps_swagger.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
