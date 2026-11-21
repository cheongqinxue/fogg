"""User-actions route and observations."""

from __future__ import annotations

import os
import uuid

import pytest

from layout.store import get_or_create_thread_layout, init_layout_store, shutdown_layout_store
from layout.user_actions import UserActionRequest, _observation_text, handle_user_action


class TestUserActions:
    @pytest.mark.unit
    def test_observation_text_format(self) -> None:
        """Observation copy includes action, coordinates, and revision transition."""
        text = _observation_text(
            action="map.viewport_changed",
            occurred_at="2026-11-09T05:00:00.000Z",
            payload={"center": {"lat": 35.68, "lng": 139.76}, "zoom": 10},
            client_revision=12,
            server_revision=13,
        )
        assert "map.viewport_changed" in text
        assert "revision now 13" in text

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_user_action_updates_layout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Accepted user-action bumps revision and appends a checkpoint message."""
        if not (os.environ.get("AGENT_DATABASE_URL") or os.environ.get("DATABASE_URL")):
            pytest.skip("DATABASE_URL not set")

        from master.agent import get_graph, reset_graph_for_tests
        from utils.checkpointing import init_checkpointer, shutdown_checkpointer

        await init_layout_store()
        await init_checkpointer()
        reset_graph_for_tests()

        thread_id = f"pytest-ua-{uuid.uuid4()}"
        try:
            await get_or_create_thread_layout(thread_id)
            body = UserActionRequest(
                action="map.viewport_changed",
                occurred_at="2026-11-09T05:00:00.000Z",
                client_revision=0,
                payload={
                    "center": {"lat": 35.68, "lng": 139.76},
                    "zoom": 10,
                },
            )
            result = await handle_user_action(thread_id, body)
            assert result.accepted is True
            assert result.revision == 1

            graph = get_graph()
            state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
            messages = state.values.get("messages") or []
            kinds = [
                m.additional_kwargs.get("kind") for m in messages if hasattr(m, "additional_kwargs")
            ]
            assert "user_action" in kinds
        finally:
            await shutdown_checkpointer()
            await shutdown_layout_store()
            reset_graph_for_tests()
