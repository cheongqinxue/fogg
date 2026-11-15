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
DAILY_USAGE_KEY_PREFIX = "gmaps:usage:daily"
WARN_KEY_PREFIX = "gmaps:quota:warned"


def current_period(now: datetime | None = None) -> str:
    """Billing period ``YYYY-MM`` in Pacific Time."""
    instant = now or datetime.now(tz=PACIFIC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=PACIFIC)
    pacific = instant.astimezone(PACIFIC)
    return f"{pacific.year:04d}-{pacific.month:02d}"


def current_day(now: datetime | None = None) -> str:
    """Billing day ``YYYY-MM-DD`` in Pacific Time."""
    instant = now or datetime.now(tz=PACIFIC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=PACIFIC)
    return instant.astimezone(PACIFIC).date().isoformat()


def _cap_for_event(sku: str) -> int:
    """Return cap for Lua (-1 = a recognized unlimited-free SKU)."""
    if sku not in SKU_FREE_CAP:
        msg = f"Quota enforcement has no verified free cap for SKU {sku!r}"
        raise ValueError(msg)
    cap = SKU_FREE_CAP[sku]
    return -1 if cap is None else cap


def _validate_events(events: list[BillableEvent]) -> None:
    """Reject unclassified SKUs instead of treating them as unlimited."""
    for event in events:
        if event.units <= 0:
            msg = f"Quota event units must be positive; received {event.units}"
            raise ValueError(msg)
        _cap_for_event(event.sku)


class UsageStore(Protocol):
    """Async usage persistence."""

    async def record(
        self, events: list[BillableEvent], period: str | None = None, day: str | None = None
    ) -> None: ...

    async def try_reserve(
        self, events: list[BillableEvent], period: str | None = None, day: str | None = None
    ) -> dict[str, int]: ...

    async def refund(
        self, events: list[BillableEvent], period: str | None = None, day: str | None = None
    ) -> None: ...

    async def totals(self, period: str | None = None) -> dict[str, int]: ...

    async def daily_totals(self, day: str | None = None) -> dict[str, int]: ...

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
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gmaps_usage_daily (
                day TEXT NOT NULL,
                sku TEXT NOT NULL,
                units INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (day, sku)
            )
            """
        )
        self._conn.commit()

    async def record(
        self,
        events: list[BillableEvent],
        period: str | None = None,
        day: str | None = None,
    ) -> None:
        """Increment SKU counters."""
        _validate_events(events)
        bucket = period or current_period()
        day_bucket = day or current_day()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            for event in merge_billable_events(events):
                self._conn.execute(
                    """
                    INSERT INTO gmaps_usage (period, sku, units) VALUES (?, ?, ?)
                    ON CONFLICT(period, sku) DO UPDATE SET units = units + excluded.units
                    """,
                    (bucket, event.sku, event.units),
                )
                self._conn.execute(
                    """
                    INSERT INTO gmaps_usage_daily (day, sku, units) VALUES (?, ?, ?)
                    ON CONFLICT(day, sku) DO UPDATE SET units = units + excluded.units
                    """,
                    (day_bucket, event.sku, event.units),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    async def try_reserve(
        self,
        events: list[BillableEvent],
        period: str | None = None,
        day: str | None = None,
    ) -> dict[str, int]:
        """Atomically increment if under cap (SQLite transaction)."""
        _validate_events(events)
        bucket = period or current_period()
        day_bucket = day or current_day()
        merged = merge_billable_events(events)
        self._conn.execute("BEGIN IMMEDIATE")
        new_totals: dict[str, int] = {}
        try:
            for event in merged:
                cap = SKU_FREE_CAP[event.sku]
                row = self._conn.execute(
                    "SELECT units FROM gmaps_usage WHERE period = ? AND sku = ?",
                    (bucket, event.sku),
                ).fetchone()
                current = int(row[0]) if row else 0
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
                self._conn.execute(
                    """
                    INSERT INTO gmaps_usage (period, sku, units) VALUES (?, ?, ?)
                    ON CONFLICT(period, sku) DO UPDATE SET units = units + excluded.units
                    """,
                    (bucket, event.sku, event.units),
                )
                self._conn.execute(
                    """
                    INSERT INTO gmaps_usage_daily (day, sku, units) VALUES (?, ?, ?)
                    ON CONFLICT(day, sku) DO UPDATE SET units = units + excluded.units
                    """,
                    (day_bucket, event.sku, event.units),
                )
                new_totals[event.sku] = current + event.units
            self._conn.commit()
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return new_totals

    async def refund(
        self,
        events: list[BillableEvent],
        period: str | None = None,
        day: str | None = None,
    ) -> None:
        """Decrement counters after a failed API call."""
        bucket = period or current_period()
        day_bucket = day or current_day()
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
            day_row = self._conn.execute(
                "SELECT units FROM gmaps_usage_daily WHERE day = ? AND sku = ?",
                (day_bucket, event.sku),
            ).fetchone()
            if day_row:
                daily_current = int(day_row[0])
                daily_refund = min(daily_current, event.units)
                if daily_refund > 0:
                    self._conn.execute(
                        "UPDATE gmaps_usage_daily SET units = units - ? WHERE day = ? AND sku = ?",
                        (daily_refund, day_bucket, event.sku),
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

    async def daily_totals(self, day: str | None = None) -> dict[str, int]:
        """Read local usage counters for one Pacific billing day."""
        bucket = day or current_day()
        rows = self._conn.execute(
            "SELECT sku, units FROM gmaps_usage_daily WHERE day = ?",
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
            from agent_utils.redis_client import get_async_redis_client
            from gmaps.settings import get_settings

            self._redis = get_async_redis_client(get_settings().redis_url)
        self._lua_supported: bool | None = None

    @staticmethod
    def _counter_key(period: str, sku: str) -> str:
        return f"{USAGE_KEY_PREFIX}:{period}:{sku}"

    @staticmethod
    def _index_key(period: str) -> str:
        return f"{USAGE_KEY_PREFIX}:{period}:{USAGE_INDEX_SUFFIX}"

    @staticmethod
    def _daily_counter_key(day: str, sku: str) -> str:
        return f"{DAILY_USAGE_KEY_PREFIX}:{day}:{sku}"

    @staticmethod
    def _daily_index_key(day: str) -> str:
        return f"{DAILY_USAGE_KEY_PREFIX}:{day}:{USAGE_INDEX_SUFFIX}"

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

    async def record(
        self,
        events: list[BillableEvent],
        period: str | None = None,
        day: str | None = None,
    ) -> None:
        """Increment counters in one pipelined round trip."""
        _validate_events(events)
        bucket = period or current_period()
        day_bucket = day or current_day()
        index_key = self._index_key(bucket)
        day_index_key = self._daily_index_key(day_bucket)
        async with self._redis.pipeline(transaction=True) as pipe:
            for event in merge_billable_events(events):
                pipe.incrby(self._counter_key(bucket, event.sku), event.units)
                pipe.sadd(index_key, event.sku)
                pipe.incrby(self._daily_counter_key(day_bucket, event.sku), event.units)
                pipe.sadd(day_index_key, event.sku)
            await pipe.execute()

    async def try_reserve(
        self,
        events: list[BillableEvent],
        period: str | None = None,
        day: str | None = None,
    ) -> dict[str, int]:
        """Atomically reserve quota with Lua or a WATCH transaction."""
        _validate_events(events)
        if await self._eval_supported():
            return await self._try_reserve_lua(events, period, day)
        return await self._try_reserve_watched(events, period, day)

    async def _try_reserve_lua(
        self,
        events: list[BillableEvent],
        period: str | None = None,
        day: str | None = None,
    ) -> dict[str, int]:
        bucket = period or current_period()
        day_bucket = day or current_day()
        merged = merge_billable_events(events)
        if not merged:
            return {}
        index_key = self._index_key(bucket)
        day_index_key = self._daily_index_key(day_bucket)
        counter_keys = [self._counter_key(bucket, event.sku) for event in merged]
        day_counter_keys = [self._daily_counter_key(day_bucket, event.sku) for event in merged]
        argv: list[str | int] = [len(merged)]
        for event in merged:
            argv.extend([event.units, _cap_for_event(event.sku), event.sku])
        raw = await self._redis.eval(
            RESERVE_QUOTA_SCRIPT,
            2 * len(counter_keys) + 2,
            index_key,
            *counter_keys,
            day_index_key,
            *day_counter_keys,
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

    async def _try_reserve_watched(
        self,
        events: list[BillableEvent],
        period: str | None = None,
        day: str | None = None,
    ) -> dict[str, int]:
        """Atomic fallback when Redis does not permit Lua scripting."""
        bucket = period or current_period()
        day_bucket = day or current_day()
        merged = merge_billable_events(events)
        if not merged:
            return {}
        keys = [self._counter_key(bucket, event.sku) for event in merged]
        day_keys = [self._daily_counter_key(day_bucket, event.sku) for event in merged]
        index_key = self._index_key(bucket)
        day_index_key = self._daily_index_key(day_bucket)
        while True:
            async with self._redis.pipeline() as pipe:
                try:
                    await pipe.watch(*keys)
                    raw_values = await pipe.mget(keys)
                    current_values = [int(value or 0) for value in raw_values]
                    for event, current in zip(merged, current_values, strict=True):
                        cap = SKU_FREE_CAP[event.sku]
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
                    pipe.multi()
                    for event, key, day_key in zip(merged, keys, day_keys, strict=True):
                        pipe.incrby(key, event.units)
                        pipe.sadd(index_key, event.sku)
                        pipe.incrby(day_key, event.units)
                        pipe.sadd(day_index_key, event.sku)
                    results = await pipe.execute()
                    return {
                        event.sku: int(results[index * 4]) for index, event in enumerate(merged)
                    }
                except redis.exceptions.WatchError:
                    continue

    async def refund(
        self,
        events: list[BillableEvent],
        period: str | None = None,
        day: str | None = None,
    ) -> None:
        """Refund reserved units after a failed Google call."""
        merged = merge_billable_events(events)
        if not merged:
            return
        bucket = period or current_period()
        day_bucket = day or current_day()
        if await self._eval_supported():
            keys = [self._counter_key(bucket, event.sku) for event in merged]
            keys.extend(self._daily_counter_key(day_bucket, event.sku) for event in merged)
            argv: list[int] = [len(merged), *[event.units for event in merged]]
            await self._redis.eval(REFUND_QUOTA_SCRIPT, len(keys), *keys, *argv)
            return
        month_keys = [self._counter_key(bucket, event.sku) for event in merged]
        day_keys = [self._daily_counter_key(day_bucket, event.sku) for event in merged]
        while True:
            async with self._redis.pipeline() as pipe:
                try:
                    await pipe.watch(*month_keys, *day_keys)
                    values = await pipe.mget([*month_keys, *day_keys])
                    month_values = [int(value or 0) for value in values[: len(merged)]]
                    day_values = [int(value or 0) for value in values[len(merged) :]]
                    pipe.multi()
                    for event, month_key, day_key, month_value, day_value in zip(
                        merged, month_keys, day_keys, month_values, day_values, strict=True
                    ):
                        pipe.set(month_key, max(0, month_value - event.units))
                        pipe.set(day_key, max(0, day_value - event.units))
                    await pipe.execute()
                    return
                except redis.exceptions.WatchError:
                    continue

    async def totals(self, period: str | None = None) -> dict[str, int]:
        """Read all SKU totals for a period (SMEMBERS + MGET)."""
        bucket = period or current_period()
        skus = await self._redis.smembers(self._index_key(bucket))
        if not skus:
            return {}
        keys = [self._counter_key(bucket, sku) for sku in skus]
        values = await self._redis.mget(keys)
        return {sku: int(value or 0) for sku, value in zip(skus, values, strict=True)}

    async def daily_totals(self, day: str | None = None) -> dict[str, int]:
        """Read local usage counters for one Pacific billing day."""
        bucket = day or current_day()
        skus = await self._redis.smembers(self._daily_index_key(bucket))
        if not skus:
            return {}
        keys = [self._daily_counter_key(bucket, sku) for sku in skus]
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
        """No-op; shared Redis clients are closed by the application lifecycle."""
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


async def build_daily_quota_summary(store: UsageStore, day: str | None = None) -> dict[str, object]:
    """Daily counters for comparison with delayed Google Cloud Billing export."""
    bucket = day or current_day()
    used = await store.daily_totals(bucket)
    all_skus = sorted(set(used) | set(SKU_FREE_CAP))
    rows = [quota_summary_row(sku, used.get(sku, 0)) for sku in all_skus]
    return {
        "day": bucket,
        "day_timezone": "America/Los_Angeles",
        "skus": rows,
        "note": "Local request attempts through gmaps; compare by SKU and billable unit.",
    }
