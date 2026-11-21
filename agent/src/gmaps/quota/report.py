"""Print local quota counts for comparison with Google Cloud Billing."""

from __future__ import annotations

import argparse
import asyncio
import json

from gmaps.quota.store import build_daily_quota_summary, get_usage_store


async def _report(day: str | None) -> None:
    store = get_usage_store()
    try:
        summary = await build_daily_quota_summary(store, day)
        print(json.dumps(summary, indent=2, sort_keys=True))
    finally:
        await store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", help="Pacific billing day YYYY-MM-DD (defaults to today)")
    args = parser.parse_args()
    asyncio.run(_report(args.day))


if __name__ == "__main__":
    main()
