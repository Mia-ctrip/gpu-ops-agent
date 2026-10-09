"""ToolExecutor — executes registered tools."""

from __future__ import annotations

from typing import Any

from .tool_registry import ToolRegistry


class ToolExecutor:
    """Execute tools from a registry."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def execute(self, tool_name: str, **kwargs: Any) -> dict:
        """Execute a tool by name with given arguments."""
        tool = self.registry.get(tool_name)
        if not tool:
            raise ValueError(f"Tool {tool_name!r} not found in registry")
        return tool.run(**kwargs)
