"""Layout sync service (integration with Postgres)."""

from __future__ import annotations

import os
import uuid

import pytest

from layout.models import LayoutDocument, LayoutSyncRequest, ProposedDelta
from layout.service import sync_layout
from layout.store import get_or_create_thread_layout, init_layout_store, shutdown_layout_store


class TestLayoutSync:
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_proposed_delta_increments_revision(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        if not (os.environ.get("AGENT_DATABASE_URL") or os.environ.get("DATABASE_URL")):
            pytest.skip("DATABASE_URL not set")
        await init_layout_store()
        thread_id = f"pytest-{uuid.uuid4()}"
        try:
            row = await get_or_create_thread_layout(thread_id)
            assert row.revision == 0

            response = await sync_layout(
                thread_id,
                LayoutSyncRequest(
                    client_revision=0,
                    proposed_delta=ProposedDelta(
                        op="map.set_viewport",
                        source="user",
                        payload={
                            "center": {"lat": 35.68, "lng": 139.76},
                            "zoom": 10,
                        },
                    ),
                ),
            )
            assert response.accepted is True
            assert response.revision == 1
            assert response.layout["map"]["viewport"]["center"]["lat"] == 35.68

            stale = await sync_layout(
                thread_id,
                LayoutSyncRequest(
                    client_revision=0,
                    proposed_delta=ProposedDelta(
                        op="map.set_viewport",
                        source="user",
                        payload={"center": {"lat": 0, "lng": 0}, "zoom": 1},
                    ),
                ),
            )
            assert stale.accepted is False
            assert stale.reject_reason == "stale_revision"
        finally:
            await shutdown_layout_store()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_pending_deltas_rejected(self) -> None:
        """Non-empty pending_deltas is not supported yet."""
        if not (os.environ.get("AGENT_DATABASE_URL") or os.environ.get("DATABASE_URL")):
            pytest.skip("DATABASE_URL not set")
        await init_layout_store()
        thread_id = f"pytest-pending-{uuid.uuid4()}"
        try:
            await get_or_create_thread_layout(thread_id)
            result = await sync_layout(
                thread_id,
                LayoutSyncRequest(
                    client_revision=0,
                    sync_mode="full",
                    layout=LayoutDocument.default_singapore().to_storage_dict(),
                    pending_deltas=[{"op": "map.set_viewport"}],
                ),
            )
            assert result.accepted is False
            assert result.reject_reason == "pending_deltas_not_supported"
        finally:
            await shutdown_layout_store()
