"""Per-run JSONL audit logger for full agent loop tracing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AuditLogger:
    """Logs every event in the agent loop to a per-run JSONL file.

    Each run creates a new file under the logs directory:
        logs/run_20260413_175407.json

    Events captured:
        - scan_start / scan_end: run metadata
        - llm_request: messages + tools sent to the LLM
        - llm_response: full content + tool calls returned
        - llm_tokens: streaming token chunks (batched)
        - tool_call / tool_error: tool execution with args, result, timing
        - stealth_block: tool blocked by stealth mode
    """

    def __init__(self, log_dir: str = "logs") -> None:
        self._dir = Path(log_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        self._path = self._dir / f"run_{ts}.json"
        self._run_id = ts

    @property
    def log_path(self) -> Path:
        """Return the path to the current run's log file."""
        return self._path

    def log(self, event: str, **fields: Any) -> None:
        """Append a single event to the run log.

        Args:
            event: Event type identifier.
            **fields: Additional fields to include in the log entry.
        """
        entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": self._run_id,
            "event": event,
            **fields,
        }
        with open(self._path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def log_scan(self, event: str, scan_type: str, **fields: Any) -> None:
        """Log scan start/end events."""
        self.log(event, scan_type=scan_type, **fields)

    def log_llm_request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        iteration: int,
    ) -> None:
        """Log the full request sent to the LLM."""
        self.log(
            "llm_request",
            iteration=iteration,
            message_count=len(messages),
            messages=messages,
            tool_count=len(tools) if tools else 0,
            tools=tools,
        )

    def log_llm_response(
        self,
        content: str,
        tool_calls: list[dict[str, Any]],
        iteration: int,
        elapsed_ms: float,
        eval_count: int | None = None,
        prompt_eval_count: int | None = None,
    ) -> None:
        """Log the full LLM response including content and tool calls."""
        self.log(
            "llm_response",
            iteration=iteration,
            content=content,
            tool_calls=tool_calls,
            elapsed_ms=elapsed_ms,
            eval_count=eval_count,
            prompt_eval_count=prompt_eval_count,
        )

    def log_llm_tokens(self, tokens: str, iteration: int) -> None:
        """Log a batch of streamed tokens."""
        if tokens:
            self.log("llm_tokens", iteration=iteration, tokens=tokens)

    def log_tool_call(
        self,
        tool: str,
        category: str,
        arguments: dict[str, Any],
        success: bool,
        execution_time_ms: float,
        result_summary: str = "",
        result_data: Any = None,
        error: str | None = None,
    ) -> None:
        """Log a tool execution event with full result data."""
        self.log(
            "tool_call" if success else "tool_error",
            tool=tool,
            category=category,
            arguments=arguments,
            success=success,
            execution_time_ms=execution_time_ms,
            result_summary=result_summary,
            result_data=result_data,
            error=error,
        )

    def log_stealth_block(self, tool: str) -> None:
        """Log when stealth mode blocks an active tool."""
        self.log("stealth_block", tool=tool)

    def log_cache_hit(self, tool: str) -> None:
        """Log when a tool result is served from cache."""
        self.log("cache_hit", tool=tool)
