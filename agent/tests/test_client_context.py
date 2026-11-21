"""Client context digest for chat turns."""

from __future__ import annotations

import pytest
from layout.client_context import ClientContextPayload, format_client_context_digest


class TestClientContextDigest:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_digest_includes_sync_and_viewport(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _no_head(_user_id: str):
            return None

        monkeypatch.setattr(
            "layout.client_context.get_layout_head",
            _no_head,
        )
        client_context = ClientContextPayload(
            revision=2,
            layout_hash="a" * 64,
            sync_status="pending",
            viewport_summary={
                "center": {"lat": 1.35, "lng": 103.82},
                "zoom": 11.5,
                "label": "Singapore",
            },
            chat={"mode": "preview"},
        )
        text = await format_client_context_digest("default", client_context)
        assert "sync_status: pending" in text
        assert "Singapore" in text
        assert "revision=2" in text
