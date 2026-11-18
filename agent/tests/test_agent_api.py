"""FastAPI agent routes (httpx + app lifespan)."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from master_agt.agent import get_graph, reset_graph_for_tests
from api.app import app
from agent_utils.checkpointing import init_checkpointer, shutdown_checkpointer
from layout.store import init_layout_store, shutdown_layout_store


@pytest.fixture
async def api_client() -> AsyncClient:
    """HTTP client with the same startup/shutdown as ``api.app`` lifespan."""
    if not (os.environ.get("AGENT_DATABASE_URL") or os.environ.get("DATABASE_URL")):
        pytest.skip("DATABASE_URL not set — integration tests require Postgres")
    await init_layout_store()
    await init_checkpointer()
    reset_graph_for_tests()
    get_graph()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    await shutdown_checkpointer()
    await shutdown_layout_store()
    reset_graph_for_tests()


class TestAgentApi:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_health(self) -> None:
        """Health response can be checked without starting external services."""
        from api.routes.v1 import health

        response = await health()
        assert response.status == "ok"

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_layout_sync_rejects_whitespace_user_id(self, api_client: AsyncClient) -> None:
        """Whitespace user id is rejected before touching the layout store."""
        if not (os.environ.get("AGENT_DATABASE_URL") or os.environ.get("DATABASE_URL")):
            pytest.skip("DATABASE_URL not set")
        response = await api_client.post(
            "/v1/users/%20/layout/sync",
            json={"client_revision": 0},
        )
        assert response.status_code == 400

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_read_layout_head_reports_revision_match(self, api_client: AsyncClient) -> None:
        """Optional revision query sets client_revision_matches."""
        if not (os.environ.get("AGENT_DATABASE_URL") or os.environ.get("DATABASE_URL")):
            pytest.skip("DATABASE_URL not set")
        user_id = "api-test-head"
        first = await api_client.get(f"/v1/users/{user_id}/layout")
        assert first.status_code == 200
        revision = first.json()["revision"]
        second = await api_client.get(f"/v1/users/{user_id}/layout?revision={revision}")
        assert second.json()["client_revision_matches"] is True
        third = await api_client.get(f"/v1/users/{user_id}/layout?revision={revision + 99}")
        assert third.json()["client_revision_matches"] is False
