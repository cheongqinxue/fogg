"""Local Phoenix tracing for the LangGraph agent."""

from __future__ import annotations

import asyncio
import os

from openinference.instrumentation.langchain import LangChainInstrumentor
from openinference.instrumentation import TraceConfig
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_provider: TracerProvider | None = None


def get_tracer(name: str):
    """Return a tracer from the configured provider, including custom compact spans."""
    if _provider is not None:
        return _provider.get_tracer(name)
    return trace.get_tracer(name)


def init_tracing() -> None:
    """Instrument LangChain once, exporting spans in a background batch."""
    global _provider
    if os.environ.get("FOGG_TRACING_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
        return
    if _provider is not None:
        return
    endpoint = os.environ.get("FOGG_TRACING_ENDPOINT", "http://127.0.0.1:16006/v1/traces")
    project = os.environ.get("FOGG_TRACING_PROJECT", "fogg-dev")
    hide_io = os.environ.get("FOGG_TRACING_HIDE_IO", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    provider = TracerProvider(resource=Resource.create({"openinference.project.name": project}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    try:
        instrument_kwargs = {"tracer_provider": provider}
        if hide_io:
            instrument_kwargs["config"] = TraceConfig(
                hide_inputs=True,
                hide_outputs=True,
                hide_input_images=True,
                hide_input_text=True,
                hide_output_text=True,
            )
        LangChainInstrumentor().instrument(**instrument_kwargs)
    except BaseException:
        provider.shutdown()
        raise
    _provider = provider


async def shutdown_tracing() -> None:
    """Stop instrumentation and flush pending spans without blocking the event loop."""
    global _provider
    provider, _provider = _provider, None
    if provider is not None:
        LangChainInstrumentor().uninstrument()
        await asyncio.to_thread(provider.shutdown)
