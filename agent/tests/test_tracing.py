"""Phoenix instrumentation lifecycle and emitted LangChain spans."""

import pytest
from langchain_core.runnables import RunnableLambda
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent_utils import tracing


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


@pytest.mark.asyncio
async def test_sensitive_browser_trace_can_hide_oversized_model_io(monkeypatch):
    calls = {}

    class FakeInstrumentor:
        def instrument(self, **kwargs):
            calls.update(kwargs)

        def uninstrument(self):
            pass

    exporter = InMemorySpanExporter()
    monkeypatch.setenv("FOGG_TRACING_ENABLED", "true")
    monkeypatch.setenv("FOGG_TRACING_HIDE_IO", "true")
    monkeypatch.setattr(tracing, "OTLPSpanExporter", lambda **_kwargs: exporter)
    monkeypatch.setattr(tracing, "BatchSpanProcessor", SimpleSpanProcessor)
    monkeypatch.setattr(tracing, "LangChainInstrumentor", FakeInstrumentor)
    tracing.init_tracing()
    try:
        config = calls["config"]
        assert config.hide_inputs is True
        assert config.hide_outputs is True
        assert config.hide_input_images is True
        assert config.hide_input_text is True
        assert config.hide_output_text is True
    finally:
        await tracing.shutdown_tracing()


def test_custom_tracer_uses_the_service_provider(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = tracing.TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, "_provider", provider)
    try:
        with tracing.get_tracer("custom-test").start_as_current_span("compact-turn"):
            pass
    finally:
        provider.shutdown()
        monkeypatch.setattr(tracing, "_provider", None)
    assert exporter.get_finished_spans()[0].name == "compact-turn"
