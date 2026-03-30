"""Tool system: BaseTool ABC, ToolRegistry with auto-discovery."""

from __future__ import annotations

import importlib
import pkgutil
import time
from abc import ABC, abstractmethod
from typing import Any

from cyberpunk.models import ToolCategory, ToolDefinition, ToolResult


class ToolExecutionError(Exception):
    """Raised when a tool fails to execute."""


class BaseTool(ABC):
    """Abstract base class for all CyberPunk tools."""

    @property
    @abstractmethod
    def definition(self) -> ToolDefinition:
        """Tool metadata: name, description, category, parameters."""

    @abstractmethod
    def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Run the tool. Return structured JSON-serializable dict."""

    @abstractmethod
    def is_available(self) -> bool:
        """Can this tool run on the current OS?"""

    def run(self, **kwargs: Any) -> ToolResult:
        """Public entry: wraps execute() with timing and error handling."""
        start = time.perf_counter()
        try:
            data = self.execute(**kwargs)
            elapsed = (time.perf_counter() - start) * 1000
            return ToolResult(
                tool_name=self.definition.name,
                success=True,
                data=data,
                execution_time_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return ToolResult(
                tool_name=self.definition.name,
                success=False,
                error=str(e),
                execution_time_ms=elapsed,
            )


class ToolRegistry:
    """Registry that auto-discovers BaseTool subclasses from the tools package."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def discover(self) -> None:
        """Import all modules in cyberpunk.tools and register BaseTool subclasses."""
        import cyberpunk.tools as tools_pkg

        for _importer, modname, _ispkg in pkgutil.iter_modules(tools_pkg.__path__):
            module = importlib.import_module(f"cyberpunk.tools.{modname}")
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseTool)
                    and attr is not BaseTool
                ):
                    tool = attr()
                    if tool.is_available():
                        self._tools[tool.definition.name] = tool

    def register(self, tool: BaseTool) -> None:
        """Manually register a tool instance."""
        self._tools[tool.definition.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_definitions(
        self,
        stealth: bool = False,
    ) -> list[ToolDefinition]:
        """Get all tool definitions, filtering active tools in stealth mode."""
        defs: list[ToolDefinition] = []
        for tool in self._tools.values():
            if stealth and tool.definition.category == ToolCategory.ACTIVE:
                continue
            defs.append(tool.definition)
        return defs

    def get_ollama_tools(self, stealth: bool = False) -> list[dict[str, Any]]:
        """Get tool definitions in Ollama schema format."""
        return [d.to_ollama_schema() for d in self.get_definitions(stealth=stealth)]

    @property
    def tools(self) -> dict[str, BaseTool]:
        return dict(self._tools)
