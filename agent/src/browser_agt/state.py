"""Graph state for a browser research task."""

from langgraph.graph import MessagesState


class BrowserAgentState(MessagesState):
    """Messages for one isolated research task; live browser objects stay outside state."""
