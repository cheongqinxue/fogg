"""GET /v1/users/{user_id}/messages."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from api.app import app
from layout.store import init_layout_store, shutdown_layout_store
from api.messages.store import init_message_store, shutdown_message_store


@pytest.fixture
async def api_client() -> AsyncClient:
    """HTTP client with the same startup/shutdown as ``api.app`` lifespan."""
    if not (os.environ.get("AGENT_DATABASE_URL") or os.environ.get("DATABASE_URL")):
        pytest.skip("DATABASE_URL not set — integration tests require Postgres")
    await init_layout_store()
    await init_message_store()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    await shutdown_message_store()
    await shutdown_layout_store()


class TestMessageHistory:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_history_returns_newest_page_in_display_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from api.messages import history
        from api.messages.store import encode_cursor

        timestamp = datetime(2026, 11, 15, 3, 20, tzinfo=UTC)
        rows = [
            {"id": 8, "role": "user", "text": "Earlier", "created_at": timestamp},
            {"id": 9, "role": "assistant", "text": "Later", "created_at": timestamp},
        ]

        async def fake_list_messages(_thread_id: str, before_id: int | None = None):
            assert before_id is None
            return rows, True

        monkeypatch.setattr(history, "list_messages", fake_list_messages)
        response = await history.list_ui_messages("unit-user")

        assert [message.id for message in response.messages] == ["8", "9"]
        assert [message.text for message in response.messages] == ["Earlier", "Later"]
        assert response.messages[0].timestamp == timestamp
        assert response.has_more is True
        assert response.next_cursor == encode_cursor(8)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_history_cursor_fetches_strictly_older_page(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from api.messages import history
        from api.messages.store import encode_cursor

        received: list[int | None] = []

        async def fake_list_messages(_thread_id: str, before_id: int | None = None):
            received.append(before_id)
            return [], False

        monkeypatch.setattr(history, "list_messages", fake_list_messages)
        result = await history.list_ui_messages("unit-user", encode_cursor(50))

        assert received == [50]
        assert result.messages == []
        assert result.has_more is False
        assert result.next_cursor is None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_history_rejects_invalid_cursor_without_store_access(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from api.messages import history

        async def should_not_load(*_args, **_kwargs):
            raise AssertionError("store should not be queried for invalid cursor")

        monkeypatch.setattr(history, "list_messages", should_not_load)
        with pytest.raises(ValueError, match="Invalid message cursor"):
            await history.list_ui_messages("unit-user", "not-a-cursor")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chat_turn_persists_user_and_final_assistant_message(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from langchain_core.messages import AIMessage

        from api.routes import chat_handlers

        stored: list[tuple[str, str, str]] = []

        async def fake_append(thread_id: str, role: str, text: str) -> None:
            stored.append((thread_id, role, text))

        async def fake_build_turn_messages(**_kwargs):
            return []

        class FakeGraph:
            async def ainvoke(self, *_args, **_kwargs):
                return {"messages": [AIMessage(content="Agent reply")]}

        monkeypatch.setattr(chat_handlers, "append_message", fake_append)
        monkeypatch.setattr(chat_handlers, "build_turn_messages", fake_build_turn_messages)
        monkeypatch.setattr(chat_handlers, "get_graph", FakeGraph)

        await chat_handlers.run_chat_turn("unit-user", chat_handlers.ChatRequest(message="Hello"))

        assert stored == [
            ("unit-user", "user", "Hello"),
            ("unit-user", "assistant", "Agent reply"),
        ]

    @pytest.mark.unit
    def test_legacy_backfill_uses_checkpoint_order_and_times(self) -> None:
        from langchain_core.messages import AIMessage, HumanMessage

        from api.messages.store import _legacy_rows

        old = SimpleNamespace(
            checkpoint={
                "ts": "2026-11-15T01:00:00+00:00",
                "channel_values": {
                    "messages": [HumanMessage(content="First"), AIMessage(content="Reply 1")]
                },
            },
        )
        new = SimpleNamespace(
            checkpoint={
                "ts": "2026-11-15T02:00:00+00:00",
                "channel_values": {
                    "messages": [
                        HumanMessage(content="First"),
                        AIMessage(content="Reply 1"),
                        HumanMessage(content="Second"),
                        AIMessage(content="Reply 2"),
                    ],
                },
            },
        )

        assert _legacy_rows([new, old]) == [
            ("user", "First", datetime(2026, 11, 15, 1, 0, tzinfo=UTC)),
            ("assistant", "Reply 1", datetime(2026, 11, 15, 1, 0, tzinfo=UTC)),
            ("user", "Second", datetime(2026, 11, 15, 2, 0, tzinfo=UTC)),
            ("assistant", "Reply 2", datetime(2026, 11, 15, 2, 0, tzinfo=UTC)),
        ]

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_list_ui_messages_empty_thread(self, api_client: AsyncClient) -> None:
        if not (os.environ.get("AGENT_DATABASE_URL") or os.environ.get("DATABASE_URL")):
            pytest.skip("DATABASE_URL not set")
        user_id = f"pytest-messages-empty-{uuid.uuid4()}"
        response = await api_client.get(f"/v1/users/{user_id}/messages")
        assert response.status_code == 200
        assert response.json() == {"messages": [], "has_more": False, "next_cursor": None}

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_get_messages_http(self, api_client: AsyncClient) -> None:
        """HTTP route returns independently stored transcript rows with stable metadata."""
        if not (os.environ.get("AGENT_DATABASE_URL") or os.environ.get("DATABASE_URL")):
            pytest.skip("DATABASE_URL not set")
        user_id = f"pytest-messages-http-{uuid.uuid4()}"
        from api.messages.store import append_message

        await append_message(user_id, "user", "User says one")
        await append_message(user_id, "assistant", "Agent says one")
        response = await api_client.get(f"/v1/users/{user_id}/messages")
        assert response.status_code == 200
        body = response.json()
        assert body["has_more"] is False
        assert body["next_cursor"] is None
        assert [message["role"] for message in body["messages"]] == ["user", "assistant"]
        assert [message["text"] for message in body["messages"]] == [
            "User says one",
            "Agent says one",
        ]
        assert all(message["id"] for message in body["messages"])
        assert all(message["timestamp"].endswith("+00:00") for message in body["messages"])
