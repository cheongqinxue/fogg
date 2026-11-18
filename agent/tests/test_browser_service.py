"""Offline contract tests for browser research delegation and isolation."""

from __future__ import annotations

import asyncio

import pytest

from browser_agt.agent import ResearchRequest, ResearchResult


def test_environment_loader_resolves_repository_root() -> None:
    from agent_utils.env import _REPO_ROOT

    assert (_REPO_ROOT / "pyproject.toml").is_file()
    assert (_REPO_ROOT / "agent" / "src" / "browser_agt").is_dir()


@pytest.mark.asyncio
async def test_debug_service_discovers_internal_bridge_when_host_port_is_unpublished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_utils import browser_endpoint

    async def unreachable(*_args: object, **_kwargs: object) -> None:
        raise OSError("host port is not published")

    async def docker(*args: str) -> bytes:
        if args[0] == "ps":
            return b"container-id\n"
        return b'{"fogg_research_api":{"IPAddress":"172.25.0.2"}}'

    monkeypatch.setattr(asyncio, "open_connection", unreachable)
    monkeypatch.setattr(browser_endpoint, "_docker", docker)
    assert await browser_endpoint.local_browser_service_url() == "http://172.25.0.2:18081"


def test_duplex_service_requires_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from browser_agt import service

    monkeypatch.setenv("BROWSER_AGENT_SERVICE_TOKEN", "test-service-token")
    with TestClient(service.app) as client:
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect("/duplex", headers=headers):
                    pass


def test_duplex_service_rejects_work_when_capacity_is_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from browser_agt import service

    monkeypatch.setenv("BROWSER_AGENT_SERVICE_TOKEN", "test-service-token")
    monkeypatch.setattr(service, "_slots", asyncio.Semaphore(0))
    with TestClient(service.app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/duplex", headers={"Authorization": "Bearer test-service-token"}
            ):
                pass


@pytest.mark.asyncio
async def test_master_and_browser_exchange_updates_over_duplex_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from master_agt import browser_tool

    monkeypatch.setenv("BROWSER_AGENT_SERVICE_TOKEN", "test-service-token")
    monkeypatch.setenv("BROWSER_AGENT_SERVICE_URL", "http://browser.test")
    steering = []

    class FakeSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def send(self, data: str) -> None:
            payload = json.loads(data)
            if payload["type"] == "start":
                assert payload["request"]["task"] == "Find a timetable"

        async def recv(self) -> str:
            if not steering:
                return json.dumps(
                    {
                        "type": "browser_guidance_request",
                        "id": "message-1",
                        "question": "Should I compare the two stations?",
                    }
                )
            return json.dumps(
                {
                    "type": "result",
                    "result": {
                        "status": "completed",
                        "answer": "Found it",
                        "sources": [],
                        "limitations": [],
                    },
                }
            )

    def connector(url: str, **kwargs):
        assert url == "ws://browser.test/duplex"
        assert kwargs["additional_headers"]["Authorization"] == "Bearer test-service-token"
        return FakeSocket()

    async def supervise(_request, message, _history):
        steering.append(message["question"])
        return "Compare timetable options."

    monkeypatch.setattr(browser_tool, "_supervise_browser_message", supervise)
    result = await browser_tool._call_research_service(
        ResearchRequest(task="Find a timetable"), websocket_factory=connector
    )
    assert result.status == "completed"
    assert result.answer == "Found it"
    assert steering == ["Should I compare the two stations?"]


@pytest.mark.asyncio
async def test_master_reports_duplex_connection_failure_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from master_agt.browser_tool import _call_research_service

    monkeypatch.setenv("BROWSER_AGENT_SERVICE_TOKEN", "test-service-token")

    def fail(*_args, **_kwargs):
        raise OSError("connection refused with secret details")

    result = await _call_research_service(
        ResearchRequest(task="Find a timetable"), websocket_factory=fail
    )
    assert result.status == "failed"
    assert "secret details" not in result.answer


def test_duplex_service_relays_browser_updates_and_master_steering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from browser_agt import service

    monkeypatch.setenv("BROWSER_AGENT_SERVICE_TOKEN", "test-service-token")

    async def fake_research(request, *, timeout_seconds, master_channel):
        assert request.task == "Find a timetable"
        instruction = await master_channel.exchange(
            kind="browser_guidance_request", payload={"question": "Which station?"}
        )
        return ResearchResult(status="completed", answer=instruction)

    monkeypatch.setattr(service, "research", fake_research)
    with TestClient(service.app) as client:
        with client.websocket_connect(
            "/duplex", headers={"Authorization": "Bearer test-service-token"}
        ) as socket:
            socket.send_json({"type": "start", "request": {"task": "Find a timetable"}})
            message = socket.receive_json()
            assert message["type"] == "browser_guidance_request"
            assert message["question"] == "Which station?"
            socket.send_json(
                {
                    "type": "master_steering",
                    "id": message["id"],
                    "instruction": "Compare the central station.",
                }
            )
            result = socket.receive_json()
    assert result["type"] == "result"
    assert result["result"]["answer"] == "Compare the central station."


def test_duplex_service_preserves_trace_context(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient
    from opentelemetry import trace

    from browser_agt import service

    monkeypatch.setenv("BROWSER_AGENT_SERVICE_TOKEN", "test-service-token")
    observed = []

    async def fake_research(*_args: object, **_kwargs: object) -> ResearchResult:
        observed.append(trace.get_current_span().get_span_context().trace_id)
        return ResearchResult(status="completed", answer="ok")

    monkeypatch.setattr(service, "research", fake_research)
    trace_id = "1234567890abcdef1234567890abcdef"
    with TestClient(service.app) as client:
        with client.websocket_connect(
            "/duplex",
            headers={
                "Authorization": "Bearer test-service-token",
                "traceparent": f"00-{trace_id}-1234567890abcdef-01",
            },
        ) as socket:
            socket.send_json({"type": "start", "request": {"task": "Find a timetable"}})
            result = socket.receive_json()
    assert result["type"] == "result"
    assert observed == [int(trace_id, 16)]


def test_duplex_disconnect_cancels_research(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    import time

    from fastapi.testclient import TestClient

    from browser_agt import service

    monkeypatch.setenv("BROWSER_AGENT_SERVICE_TOKEN", "test-service-token")
    started, cancelled = threading.Event(), threading.Event()

    async def pending_research(*_args: object, **_kwargs: object) -> ResearchResult:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(service, "research", pending_research)
    with TestClient(service.app) as client:
        with client.websocket_connect(
            "/duplex", headers={"Authorization": "Bearer test-service-token"}
        ) as socket:
            socket.send_json({"type": "start", "request": {"task": "Find a timetable"}})
            assert started.wait(timeout=1)
        deadline = time.monotonic() + 1
        while not cancelled.is_set() and time.monotonic() < deadline:
            time.sleep(0.01)
    assert cancelled.is_set()
