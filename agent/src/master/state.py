"""Typed state carried between the ReAct model and tool nodes."""

from langgraph.graph import MessagesState


class AgentState(MessagesState):
    """Conversation state plus ephemeral internal tool-evaluation feedback."""

    tool_judge_feedback: str | None
