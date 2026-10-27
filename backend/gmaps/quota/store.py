"""Persist usage counters (Redis default; SQLite optional fallback)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

import redis.exceptions
from redis.asyncio import Redis

from gmaps.errors import GmapsQuotaExceededError
from gmaps.quota.caps import SKU_FREE_CAP
from gmaps.quota.lua_scripts import REFUND_QUOTA_SCRIPT, RESERVE_QUOTA_SCRIPT
from gmaps.quota.types import BillableEvent, merge_billable_events

PACIFIC = ZoneInfo("America/Los_Angeles")
StoreBackend = Literal["sqlite", "redis"]

USAGE_KEY_PREFIX = "gmaps:usage"
USAGE_INDEX_SUFFIX = "_index"
WARN_KEY_PREFIX = "gmaps:quota:warned"


def current_period(now: datetime | None = None) -> str:
    """Billing period ``YYYY-MM`` in Pacific Time."""
    instant = now or datetime.now(tz=PACIFIC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=PACIFIC)
    pacific = instant.astimezone(PACIFIC)
    return f"{pacific.year:04d}-{pacific.month:02d}"


def _cap_for_event(sku: str) -> int:
    """Return cap for Lua (-1 = unlimited)."""
    cap = SKU_FREE_CAP.get(sku)
    return -1 if cap is None else cap


class UsageStore(Protocol):
    """Async usage persistence."""

    async def record(self, events: list[BillableEvent], period: str | None = None) -> None: ...

    async def try_reserve(
        self, events: list[BillableEvent], period: str | None = None
    ) -> dict[str, int]: ...

    async def refund(self, events: list[BillableEvent], period: str | None = None) -> None: ...

    async def totals(self, period: str | None = None) -> dict[str, int]: ...

    async def quota_warning_already_logged(self, sku: str, period: str | None = None) -> bool: ...

    async def mark_quota_warning_logged(self, sku: str, period: str | None = None) -> None: ...

    async def close(self) -> None: ...


class SqliteUsageStore:
    """SQLite fallback when Redis is unavailable."""

    def __init__(self, db_path: str) -> None:
        """Open or create the database file."""
        from pathlib import Path

        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gmaps_usage (
                period TEXT NOT NULL,
                sku TEXT NOT NULL,
                units INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (period, sku)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gmaps_quota_warned (
                period TEXT NOT NULL,
                sku TEXT NOT NULL,
                PRIMARY KEY (period, sku)
            )
            """
        )
        self._conn.commit()

    async def record(self, events: list[BillableEvent], period: str | None = None) -> None:
        """Increment SKU counters."""
        bucket = period or current_period()
        for event in merge_billable_events(events):
            self._conn.execute(
                """
                INSERT INTO gmaps_usage (period, sku, units) VALUES (?, ?, ?)
                ON CONFLICT(period, sku) DO UPDATE SET units = units + excluded.units
                """,
                (bucket, event.sku, event.units),
            )
        self._conn.commit()

    async def try_reserve(
        self, events: list[BillableEvent], period: str | None = None
    ) -> dict[str, int]:
        """Atomically increment if under cap (SQLite transaction)."""
        bucket = period or current_period()
        merged = merge_billable_events(events)
        self._conn.execute("BEGIN IMMEDIATE")
        new_totals: dict[str, int] = {}
        try:
            for event in merged:
                cap = SKU_FREE_CAP.get(event.sku)
                row = self._conn.execute(
                    "SELECT units FROM gmaps_usage WHERE period = ? AND sku = ?",
                    (bucket, event.sku),
                ).fetchone()
                current = int(row[0]) if row else 0
                if cap is not None and current + event.units > cap:
                    self._conn.execute("ROLLBACK")
                    msg = (
                        f"Local Google Maps free-tier cap exceeded for {event.sku}: "
                        f"used {current}, cap {cap}, requested {event.units}"
                    )
                    raise GmapsQuotaExceededError(
                        msg,
                        sku=event.sku,
                        used=current,
                        cap=cap,
                        units_requested=event.units,
                    )
                self._conn.execute(
                    """
                    INSERT INTO gmaps_usage (period, sku, units) VALUES (?, ?, ?)
                    ON CONFLICT(period, sku) DO UPDATE SET units = units + excluded.units
                    """,
                    (bucket, event.sku, event.units),
                )
                new_totals[event.sku] = current + event.units
            self._conn.commit()
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return new_totals

    async def refund(self, events: list[BillableEvent], period: str | None = None) -> None:
        """Decrement counters after a failed API call."""
        bucket = period or current_period()
        for event in merge_billable_events(events):
            row = self._conn.execute(
                "SELECT units FROM gmaps_usage WHERE period = ? AND sku = ?",
                (bucket, event.sku),
            ).fetchone()
            if not row:
                continue
            current = int(row[0])
            refund = min(current, event.units)
            if refund <= 0:
                continue
            self._conn.execute(
                """
                UPDATE gmaps_usage SET units = units - ? WHERE period = ? AND sku = ?
                """,
                (refund, bucket, event.sku),
            )
        self._conn.commit()

    async def totals(self, period: str | None = None) -> dict[str, int]:
        """Return usage by SKU."""
        bucket = period or current_period()
        rows = self._conn.execute(
            "SELECT sku, units FROM gmaps_usage WHERE period = ?",
            (bucket,),
        ).fetchall()
        return {sku: units for sku, units in rows}

    async def quota_warning_already_logged(self, sku: str, period: str | None = None) -> bool:
        """Whether a threshold warning was already emitted for this SKU."""
        bucket = period or current_period()
        row = self._conn.execute(
            "SELECT 1 FROM gmaps_quota_warned WHERE period = ? AND sku = ?",
            (bucket, sku),
        ).fetchone()
        return row is not None

    async def mark_quota_warning_logged(self, sku: str, period: str | None = None) -> None:
        """Record that a threshold warning was emitted."""
        bucket = period or current_period()
        self._conn.execute(
            "INSERT OR IGNORE INTO gmaps_quota_warned (period, sku) VALUES (?, ?)",
            (bucket, sku),
        )
        self._conn.commit()

    async def close(self) -> None:
        """Close the connection."""
        self._conn.close()


class RedisUsageStore:
    """Fast Redis counters keyed by billing period and SKU."""

    def __init__(self, redis_client: Redis | None = None) -> None:
        """Use shared Redis client or an injected client (tests).

        Args:
            redis_client: Optional Redis instance; defaults to app singleton.
        """
        if redis_client is not None:
            self._redis = redis_client
        else:
            from gmaps.redis_client import get_redis

            self._redis = get_redis()
        self._lua_supported: bool | None = None

    @staticmethod
    def _counter_key(period: str, sku: str) -> str:
        return f"{USAGE_KEY_PREFIX}:{period}:{sku}"

    @staticmethod
    def _index_key(period: str) -> str:
        return f"{USAGE_KEY_PREFIX}:{period}:{USAGE_INDEX_SUFFIX}"

    @staticmethod
    def _warn_key(period: str, sku: str) -> str:
        return f"{WARN_KEY_PREFIX}:{period}:{sku}"

    async def _eval_supported(self) -> bool:
        if self._lua_supported is not None:
            return self._lua_supported
        try:
            result = await self._redis.eval("return 1", 0)  # type: ignore[misc]
            self._lua_supported = int(result) == 1
        except redis.exceptions.ResponseError:
            self._lua_supported = False
        return self._lua_supported

    async def record(self, events: list[BillableEvent], period: str | None = None) -> None:
        """Increment counters in one pipelined round trip."""
        bucket = period or current_period()
        index_key = self._index_key(bucket)
        async with self._redis.pipeline(transaction=False) as pipe:
            for event in merge_billable_events(events):
                pipe.incrby(self._counter_key(bucket, event.sku), event.units)
                pipe.sadd(index_key, event.sku)
            await pipe.execute()

    async def try_reserve(
        self, events: list[BillableEvent], period: str | None = None
    ) -> dict[str, int]:
        """Atomically reserve quota (Lua on Redis; sequential check on test doubles)."""
        if await self._eval_supported():
            return await self._try_reserve_lua(events, period)
        return await self._try_reserve_sequential(events, period)

    async def _try_reserve_lua(
        self, events: list[BillableEvent], period: str | None = None
    ) -> dict[str, int]:
        bucket = period or current_period()
        merged = merge_billable_events(events)
        if not merged:
            return {}
        index_key = self._index_key(bucket)
        counter_keys = [self._counter_key(bucket, event.sku) for event in merged]
        argv: list[str | int] = [len(merged)]
        for event in merged:
            argv.extend([event.units, _cap_for_event(event.sku), event.sku])
        raw = await self._redis.eval(
            RESERVE_QUOTA_SCRIPT,
            len(counter_keys) + 1,
            index_key,
            *counter_keys,
            *argv,
        )
        if int(raw[0]) == 0:
            sku = str(raw[1])
            used = int(raw[2])
            cap = int(raw[3])
            units = next(item.units for item in merged if item.sku == sku)
            msg = (
                f"Local Google Maps free-tier cap exceeded for {sku}: "
                f"used {used}, cap {cap}, requested {units}"
            )
            raise GmapsQuotaExceededError(
                msg,
                sku=sku,
                used=used,
                cap=cap,
                units_requested=units,
            )
        return {event.sku: int(raw[index + 1]) for index, event in enumerate(merged)}

    async def _try_reserve_sequential(
        self, events: list[BillableEvent], period: str | None = None
    ) -> dict[str, int]:
        """Fallback when ``EVAL`` is unavailable (e.g. fakeredis in unit tests)."""
        bucket = period or current_period()
        merged = merge_billable_events(events)
        new_totals: dict[str, int] = {}
        for event in merged:
            key = self._counter_key(bucket, event.sku)
            current = int(await self._redis.get(key) or 0)
            cap = SKU_FREE_CAP.get(event.sku)
            if cap is not None and current + event.units > cap:
                msg = (
                    f"Local Google Maps free-tier cap exceeded for {event.sku}: "
                    f"used {current}, cap {cap}, requested {event.units}"
                )
                raise GmapsQuotaExceededError(
                    msg,
                    sku=event.sku,
                    used=current,
                    cap=cap,
                    units_requested=event.units,
                )
        index_key = self._index_key(bucket)
        async with self._redis.pipeline(transaction=False) as pipe:
            for event in merged:
                key = self._counter_key(bucket, event.sku)
                pipe.incrby(key, event.units)
                pipe.sadd(index_key, event.sku)
            results = await pipe.execute()
        for index, event in enumerate(merged):
            new_totals[event.sku] = int(results[index * 2])
        return new_totals

    async def refund(self, events: list[BillableEvent], period: str | None = None) -> None:
        """Refund reserved units after a failed Google call."""
        merged = merge_billable_events(events)
        if not merged:
            return
        bucket = period or current_period()
        if await self._eval_supported():
            keys = [self._counter_key(bucket, event.sku) for event in merged]
            argv: list[int] = [len(merged), *[event.units for event in merged]]
            await self._redis.eval(REFUND_QUOTA_SCRIPT, len(keys), *keys, *argv)
            return
        for event in merged:
            key = self._counter_key(bucket, event.sku)
            current = int(await self._redis.get(key) or 0)
            refund = min(current, event.units)
            if refund > 0:
                await self._redis.decrby(key, refund)

    async def totals(self, period: str | None = None) -> dict[str, int]:
        """Read all SKU totals for a period (SMEMBERS + MGET)."""
        bucket = period or current_period()
        skus = await self._redis.smembers(self._index_key(bucket))
        if not skus:
            return {}
        keys = [self._counter_key(bucket, sku) for sku in skus]
        values = await self._redis.mget(keys)
        return {sku: int(value or 0) for sku, value in zip(skus, values, strict=True)}

    async def quota_warning_already_logged(self, sku: str, period: str | None = None) -> bool:
        """Whether a threshold warning was already emitted for this SKU."""
        bucket = period or current_period()
        return bool(await self._redis.exists(self._warn_key(bucket, sku)))

    async def mark_quota_warning_logged(self, sku: str, period: str | None = None) -> None:
        """Record that a threshold warning was emitted."""
        bucket = period or current_period()
        await self._redis.set(self._warn_key(bucket, sku), "1")

    async def close(self) -> None:
        """No-op; shared Redis client is closed via ``close_redis()``."""
        return None


def quota_summary_row(sku: str, used: int) -> dict[str, int | str | None]:
    """One SKU row with free tier remaining."""
    cap = SKU_FREE_CAP.get(sku)
    remaining = None if cap is None else max(cap - used, 0)
    return {"sku": sku, "used": used, "free_cap": cap, "remaining": remaining}


async def build_quota_summary(store: UsageStore, period: str | None = None) -> dict[str, object]:
    """Full quota snapshot for dashboards or CLI."""
    bucket = period or current_period()
    used = await store.totals(bucket)
    all_skus = sorted(set(used) | set(SKU_FREE_CAP))
    rows = [quota_summary_row(sku, used.get(sku, 0)) for sku in all_skus if sku != "unknown"]
    return {
        "period": bucket,
        "period_timezone": "America/Los_Angeles",
        "skus": rows,
        "note": "Counts are local estimates for calls through gmaps client.",
    }
