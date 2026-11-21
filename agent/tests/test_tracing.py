"""Phoenix instrumentation lifecycle and emitted LangChain spans."""

import pytest
from langchain_core.runnables import RunnableLambda
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from utils import tracing


@pytest.mark.asyncio
async def test_tracing_captures_langchain_spans_and_shutdown(monkeypatch):
    exporter = InMemorySpanExporter()
    monkeypatch.setenv("FOGG_TRACING_ENABLED", "true")
    monkeypatch.setenv("FOGG_TRACING_PROJECT", "test-project")
    monkeypatch.setattr(tracing, "OTLPSpanExporter", lambda **_kwargs: exporter)
    monkeypatch.setattr(tracing, "BatchSpanProcessor", SimpleSpanProcessor)
    tracing.init_tracing()
    try:
        runnable = RunnableLambda(lambda value: value + " response").with_config(
            run_name="test-agent"
        )
        assert await runnable.ainvoke("hello") == "hello response"
    finally:
        await tracing.shutdown_tracing()
    spans = exporter.get_finished_spans()
    assert any(span.name == "test-agent" for span in spans)
    assert spans[0].resource.attributes["openinference.project.name"] == "test-project"
    assert tracing._provider is None


@pytest.mark.asyncio
async def test_disabled_tracing_creates_no_provider(monkeypatch):
    monkeypatch.setenv("FOGG_TRACING_ENABLED", "false")
    tracing.init_tracing()
    assert tracing._provider is None
    await tracing.shutdown_tracing()
