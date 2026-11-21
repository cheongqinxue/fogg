"""Dev reset endpoint."""

from __future__ import annotations

import os
import uuid

import pytest
from api.dev_reset import DevResetRequest, reset_agent_state
from api.messages.store import append_message
from backend.database import init_database, shutdown_database
from layout.store import get_or_create_user_layout
from utils.checkpointing import init_checkpointer, shutdown_checkpointer


class TestDevReset:
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_reset_single_thread(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Deleting one thread removes layout and checkpoint messages."""
        if not (os.environ.get("AGENT_DATABASE_URL") or os.environ.get("DATABASE_URL")):
            pytest.skip("DATABASE_URL not set")
        monkeypatch.setenv("AGENT_DEV_RESET_ENABLED", "true")
        await init_database()
        await init_checkpointer()
        account_id = f"pytest-reset-{uuid.uuid4()}"
        try:
            await get_or_create_user_layout(account_id)
            await append_message(account_id, "user", "hello")
            graph = __import__("master.agent", fromlist=["get_graph"]).get_graph()
            from langchain_core.messages import HumanMessage

            await graph.aupdate_state(
                {"configurable": {"thread_id": account_id}},
                {"messages": [HumanMessage(content="hello")]},
            )
            result = await reset_agent_state(DevResetRequest(account_id=account_id))
            assert result.layout_rows_removed == 1
            state = await graph.aget_state({"configurable": {"thread_id": account_id}})
            assert not state.values.get("messages")
        finally:
            await shutdown_checkpointer()
            await shutdown_database()
