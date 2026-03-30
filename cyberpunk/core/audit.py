"""Append-only JSONL audit logger."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLogger:
    """Logs tool calls and agent events to an append-only JSONL file."""

    def __init__(self, log_path: str = "~/.cyberpunk/audit.log") -> None:
        self._path = Path(log_path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, **fields: Any) -> None:
        """Append a single event to the audit log.

        Args:
            event: Event type (tool_call, tool_error, llm_request, etc.).
            **fields: Additional fields to include in the log entry.
        """
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
        with open(self._path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def log_tool_call(
        self,
        tool: str,
        category: str,
        arguments: dict[str, Any],
        success: bool,
        execution_time_ms: float,
        result_summary: str = "",
        error: str | None = None,
    ) -> None:
        """Log a tool execution event."""
        self.log(
            "tool_call" if success else "tool_error",
            tool=tool,
            category=category,
            arguments=arguments,
            success=success,
            execution_time_ms=execution_time_ms,
            result_summary=result_summary,
            error=error,
        )

    def log_stealth_block(self, tool: str) -> None:
        """Log when stealth mode blocks an active tool."""
        self.log("stealth_block", tool=tool)

    def log_scan(self, event: str, scan_type: str, **fields: Any) -> None:
        """Log scan start/end events."""
        self.log(event, scan_type=scan_type, **fields)
