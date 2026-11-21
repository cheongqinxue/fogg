"""Build LangGraph message lists for a chat turn."""

from __future__ import annotations

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from layout.client_context import ClientContextPayload, format_client_context_digest


async def build_turn_messages(
    *,
    message: str,
    account_id: str,
    client_context: ClientContextPayload | None = None,
) -> list[BaseMessage]:
    """Return messages to append for this turn (context digest + user text).

    Args:
        message: User text for this turn.
        account_id: Conversation partition key (LangGraph ``thread_id``).
        client_context: Optional layout/sync hint from the client.

    Returns:
        List of LangChain messages for ``ainvoke`` / ``astream_events``.
    """
    messages: list[BaseMessage] = []
    if client_context is not None:
        digest = await format_client_context_digest(account_id, client_context)
        messages.append(
            SystemMessage(
                content=digest,
                additional_kwargs={"kind": "client_context"},
            ),
        )
    messages.append(HumanMessage(content=message))
    return messages
