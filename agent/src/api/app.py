"""FastAPI wrapper around the compiled LangGraph ReAct agent."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from backend.accounts import seed_debug_account
from backend.database import init_database, shutdown_database
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from master import agent as agent_module
from utils.checkpointing import get_checkpointer, init_checkpointer, shutdown_checkpointer
from utils.kms import close_kms_client
from utils.redis_client import close_async_redis_clients
from utils.settings import get_settings
from utils.tracing import init_tracing, shutdown_tracing

from api.dev_reset import dev_reset_enabled
from api.messages.store import backfill_checkpoint_transcripts
from api.routes.dev import router as dev_router
from api.routes.v1 import router as v1_router


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    try:
        init_tracing()
        await init_database()
        await seed_debug_account()
        await init_checkpointer()
        await backfill_checkpoint_transcripts(get_checkpointer())
        agent_module.reset_graph_for_tests()
        agent_module.get_graph()
        yield
    finally:
        await shutdown_tracing()
        await shutdown_checkpointer()
        await shutdown_database()
        await close_kms_client()
        await close_async_redis_clients()


app = FastAPI(title="Travel agent API", version="0.1.0", lifespan=_lifespan)


def _cors_origins() -> list[str]:
    return get_settings().cors_origins


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
