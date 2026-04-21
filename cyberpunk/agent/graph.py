"""LangGraph ``StateGraph`` wiring for the CyberPunk agent."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode


class AgentState(TypedDict):
    """State threaded through the graph.

    Attributes:
        messages: The full conversation. ``add_messages`` is LangGraph's
            append-only reducer for message lists.
        iteration: Count of LLM-agent turns completed. Incremented by the
            ``agent`` node on every call.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    iteration: int


SUMMARIZE_PROMPT = (
    "You have reached the maximum number of tool calls. "
    "Summarize your findings based on the data collected so far."
)


def build_graph(
    model: BaseChatModel,
    tools: list[BaseTool],
    max_iterations: int,
) -> CompiledStateGraph[AgentState, AgentState, AgentState]:
    """Compile the agent StateGraph.

    Topology::

        START -> agent -> (tool_calls?) -> tools -> agent
                       -> (iteration >= max?) -> summarize -> END
                       -> else -> END

    The conditional edge checks **after** the agent node runs (i.e. after the
    iteration counter is incremented), so ``iteration >= max_iterations``
    triggers the summarize path on the turn that *hits* the cap, preserving
    the pre-migration behavior where the 16th call would be the summary call.

    Args:
        model: A chat model that supports ``bind_tools``. Tools are bound
            inside this function — do not bind beforehand.
        tools: Per-run, wrapped tools from
            :func:`cyberpunk.agent.tool_wrapper.wrap_tools_for_run`.
        max_iterations: Hard cap on LLM turns before forcing a summary.

    Returns:
        A compiled graph. Invoke it with ``.invoke(state, config=...)`` or
        stream it with ``.stream(...)``.
    """
    model_with_tools = model.bind_tools(tools)
    # ``model`` (no tools) is used for the summarization pass so the LLM
    # can't try to call a tool when we've explicitly told it we're out of
    # tool budget.

    def agent_node(state: AgentState) -> dict[str, Any]:
        """Call the chat model with tools bound and append its response."""
        response = model_with_tools.invoke(state["messages"])
        return {"messages": [response], "iteration": state["iteration"] + 1}

    def summarize_node(state: AgentState) -> dict[str, Any]:
        """Final LLM turn when the iteration cap is hit — no tools bound."""
        nudge = HumanMessage(content=SUMMARIZE_PROMPT)
        response = model.invoke([*state["messages"], nudge])
        return {"messages": [nudge, response]}

    def should_continue(state: AgentState) -> str:
        """Route out of the agent node: tools, summarize, or end."""
        if state["iteration"] >= max_iterations:
            return "summarize"
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        # Empty AIMessage (no content, no tool calls) indicates the model
        # stalled — often a harmony/channel parsing glitch. Force a summary
        # pass instead of terminating silently with no output.
        if isinstance(last, AIMessage) and not (
            isinstance(last.content, str) and last.content.strip()
        ):
            return "summarize"
        return "end"

    graph: StateGraph[AgentState, AgentState, AgentState] = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(tools))
    graph.add_node("summarize", summarize_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "summarize": "summarize", "end": END},
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("summarize", END)

    return graph.compile()
