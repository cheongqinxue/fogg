"""LangGraph Postgres checkpointer for the travel agent."""

from __future__ import annotations

import os

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from utils.checkpointing import get_checkpointer, init_checkpointer, shutdown_checkpointer


class TestAgentCheckpoint:
    @pytest.mark.unit
    def test_default_database_url_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from utils.settings import AppSettings

        monkeypatch.delenv("AGENT_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("COMPOSE_PORT_POSTGRES", "15432")
        settings = AppSettings(_env_file=None)
        assert settings.database_url == "postgresql://fogg:fogg@127.0.0.1:15432/fogg"

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_thread_state_accumulates_messages(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        url = os.environ.get("AGENT_DATABASE_URL") or os.environ.get("DATABASE_URL")
        if not url:
            pytest.skip("DATABASE_URL not set — start compose Postgres or export connection string")

        monkeypatch.setenv("DATABASE_URL", url)
        await init_checkpointer()

        model = FakeListChatModel(responses=["Reply one.", "Reply two."])
        graph = create_agent(
            model,
            tools=[],
            system_prompt="Test.",
            checkpointer=get_checkpointer(),
        )
        config = {"configurable": {"thread_id": "pytest-checkpoint-thread"}}
        await graph.ainvoke({"messages": [("user", "first")]}, config)
        await graph.ainvoke({"messages": [("user", "second")]}, config)
        snapshot = await graph.aget_state(config)
        roles = [getattr(m, "type", None) or m[0] for m in snapshot.values["messages"]]
        assert roles.count("human") == 2
        assert roles.count("ai") == 2
        await shutdown_checkpointer()
