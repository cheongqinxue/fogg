"""FastAPI wrapper around the compiled LangGraph ReAct agent."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from graph import agent as agent_module
from graph.checkpointing import get_checkpointer, init_checkpointer, shutdown_checkpointer
from agent_utils.env import load_repo_dotenv
from layout.store import init_layout_store, shutdown_layout_store
from api.messages.store import (
    backfill_checkpoint_transcripts,
    init_message_store,
    shutdown_message_store,
)
from api.dev_reset import dev_reset_enabled
from api.routes.dev import router as dev_router
from api.routes.v1 import router as v1_router
from agent_utils.redis_client import close_async_redis_clients
from agent_utils.tracing import init_tracing, shutdown_tracing

load_repo_dotenv()


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    try:
        init_tracing()
        await init_layout_store()
        await init_message_store()
        await init_checkpointer()
        await backfill_checkpoint_transcripts(get_checkpointer())
        agent_module.reset_graph_for_tests()
        agent_module.get_graph()
        yield
    finally:
        await shutdown_tracing()
        await shutdown_checkpointer()
        await shutdown_message_store()
        await shutdown_layout_store()
        await close_async_redis_clients()


app = FastAPI(title="Travel agent API", version="0.1.0", lifespan=_lifespan)


def _cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "*").strip()
    if raw == "*":
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router)
if dev_reset_enabled():
    app.include_router(dev_router)
