#!/usr/bin/env python3
"""Run two live research scenarios sequentially through the local browser service."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

from agent_utils.env import load_repo_dotenv
from agent_utils.browser_endpoint import local_browser_service_url

SCENARIOS = (
    (
        "sp500",
        "Find the latest available S&P 500 index value and its gain or loss compared with one week earlier. Include the dates, value, and percentage change, and cite sources.",
    ),
    (
        "busan_supper",
        "Research where locals in Busan go for supper. Provide specific areas or venues, evidence for the recommendations, opening hours if available, and source URLs.",
    ),
)


async def main() -> None:
    load_repo_dotenv()
    token = os.environ.get("BROWSER_AGENT_SERVICE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Set BROWSER_AGENT_SERVICE_TOKEN in the root .env")
    port = os.environ.get("COMPOSE_PORT_BROWSER_RESEARCH", "18081")
    endpoint = os.environ.get("BROWSER_AGENT_SERVICE_URL") or await local_browser_service_url(
        int(port)
    )
    root = Path(__file__).resolve().parents[1] / ".data" / "browser-live-tests"
    destination = root / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination.mkdir(parents=True, mode=0o700)
    async with httpx.AsyncClient(timeout=200, trust_env=False) as client:
        for name, task in SCENARIOS:
            print(f"Running {name}...", flush=True)
            started = datetime.now(UTC)
            try:
                response = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {token}"},
                    json={"task": task, "starting_urls": []},
                )
                response.raise_for_status()
                result = response.json()
            except (httpx.HTTPError, ValueError) as error:
                result = {
                    "status": "failed",
                    "answer": "Browser service request failed.",
                    "limitations": [type(error).__name__],
                }
            record = {
                "task": task,
                "started_at": started.isoformat(),
                "finished_at": datetime.now(UTC).isoformat(),
                "result": result,
            }
            path = destination / f"{name}.json"
            await asyncio.to_thread(
                path.write_text, json.dumps(record, indent=2, ensure_ascii=False) + "\n"
            )
            print(f"{name}: {record['result'].get('status', 'unknown')} ({path})", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
