"""Quota tracking types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BillableEvent:
    """Billable units attributed to one SKU for a single API call."""

    sku: str
    units: int
    note: str | None = None


def merge_billable_events(events: list[BillableEvent]) -> list[BillableEvent]:
    """Combine multiple lines for the same SKU into one event."""
    totals: dict[str, int] = {}
    for event in events:
        totals[event.sku] = totals.get(event.sku, 0) + event.units
    return [BillableEvent(sku=sku, units=units) for sku, units in sorted(totals.items())]
