"""Typed state carried between the ReAct model and tool nodes."""

from langgraph.graph import MessagesState


class AgentState(MessagesState):
    """Conversation state; messages are appended using LangGraph's reducer."""
