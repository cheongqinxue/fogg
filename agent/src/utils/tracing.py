"""Local Phoenix tracing for the LangGraph agent."""

from __future__ import annotations

import asyncio

from utils.settings import get_settings

from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_provider: TracerProvider | None = None


def init_tracing() -> None:
    """Instrument LangChain once, exporting spans in a background batch."""
    global _provider
    settings = get_settings()
    if not settings.fogg_tracing_enabled:
        return
    if _provider is not None:
        return
    endpoint = settings.fogg_tracing_endpoint
    project = settings.fogg_tracing_project
    provider = TracerProvider(resource=Resource.create({"openinference.project.name": project}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    try:
        LangChainInstrumentor().instrument(tracer_provider=provider)
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
