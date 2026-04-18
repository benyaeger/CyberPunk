"""Per-run wrapping of LangChain tools: caching, stealth gate, status + audit."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from langchain_core.tools import BaseTool, StructuredTool

if TYPE_CHECKING:
    from cyberpunk.agent.status import StatusDisplay
    from cyberpunk.core.audit import AuditLogger


def wrap_tools_for_run(
    tools: list[BaseTool],
    *,
    stealth: bool,
    cache: dict[str, str],
    status: StatusDisplay,
    audit: AuditLogger,
) -> list[BaseTool]:
    """Wrap each tool with per-run side-effects.

    Every wrapper:

    1. Checks ``cache`` for a prior result with identical arguments and
       returns it unchanged (populating the status history with ``↺``).
    2. Enforces stealth mode as a **second layer** of defense. The first
       layer lives in :func:`cyberpunk.tools.available_tools`, which never
       binds active tools to the model in stealth mode. This second check
       exists because LLMs occasionally hallucinate tool names that used to
       be available; this ensures such a call still gets blocked.
    3. Times the underlying invocation and routes success / failure into
       both the status display and the audit log, so the graph code stays
       free of UI/audit plumbing.

    The wrapper always returns a **string** (JSON for success, an ``Error:``
    prefix for failure) because that is what LangGraph's ``ToolNode`` feeds
    into the resulting ``ToolMessage``. Returning structured data would work
    too, but keeping it as a string matches what the LLM sees in the
    conversation history.

    Args:
        tools: The tools to wrap — typically ``available_tools(stealth)``.
        stealth: Whether stealth mode is active.
        cache: Per-run result cache. Mutated in place; keys are
            ``"{tool_name}:{sorted args tuple}"``.
        status: The live status display.
        audit: The per-run audit logger.

    Returns:
        A new list of ``StructuredTool`` instances suitable for binding via
        ``model.bind_tools(...)`` and passing to ``ToolNode``.
    """
    wrapped: list[BaseTool] = []
    for raw in tools:
        wrapped.append(_wrap_one(raw, stealth=stealth, cache=cache, status=status, audit=audit))
    return wrapped


def _wrap_one(
    raw: BaseTool,
    *,
    stealth: bool,
    cache: dict[str, str],
    status: StatusDisplay,
    audit: AuditLogger,
) -> BaseTool:
    """Build a single wrapped tool. See :func:`wrap_tools_for_run`."""
    tags = raw.tags or []
    category = next((t for t in tags if t in ("passive", "active", "analysis")), "unknown")

    def _invoke(**kwargs: Any) -> str:
        cache_key = f"{raw.name}:{sorted(kwargs.items())}"

        if cache_key in cache:
            audit.log_cache_hit(raw.name)
            status.log_cached(raw.name)
            return cache[cache_key]

        if stealth and "active" in tags:
            # Defense-in-depth stealth block. The model shouldn't have been
            # able to pick this tool — it wasn't in the bound list — but if
            # it emitted a tool_call for it anyway (model hallucination or
            # stale plan), we refuse execution here.
            audit.log_stealth_block(raw.name)
            status.log_stealth_block(raw.name)
            return f"Error: Tool '{raw.name}' blocked: stealth mode is active."

        start = time.perf_counter()
        try:
            # LangChain tools take the argument dict verbatim. For our
            # zero-argument tools this is ``{}``; the machinery still works
            # for future tools with declared parameters.
            data = raw.invoke(kwargs)
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            error_message = f"{type(e).__name__}: {e}"
            audit.log_tool_call(
                tool=raw.name,
                category=category,
                arguments=kwargs,
                success=False,
                execution_time_ms=elapsed_ms,
                result_data=None,
                error=error_message,
            )
            status.log_tool_error(raw.name, error_message)
            return f"Error: {error_message}"

        elapsed_ms = (time.perf_counter() - start) * 1000

        # Build a short human-readable summary for the audit log. Tools
        # typically return a ``count`` key; prefer that when present.
        summary = ""
        if isinstance(data, dict):
            count = data.get("count")
            if count is not None:
                summary = f"Found {count} entries"

        audit.log_tool_call(
            tool=raw.name,
            category=category,
            arguments=kwargs,
            success=True,
            execution_time_ms=elapsed_ms,
            result_summary=summary,
            result_data=data,
        )
        status.log_tool_success(raw.name, elapsed_ms)

        serialized = json.dumps(data, default=str)
        cache[cache_key] = serialized
        return serialized

    return StructuredTool.from_function(
        func=_invoke,
        name=raw.name,
        description=raw.description,
        args_schema=raw.args_schema,
        tags=raw.tags,
    )
