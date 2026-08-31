"""ToolExecutor — validates args, calls tool.run(), wraps exceptions."""

from __future__ import annotations

import logging
import time
from typing import Any

from models.agent import ToolCallRecord
from .tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def execute(self, tool_name: str, args: dict) -> ToolCallRecord:
        """Execute a single tool call.  Always returns a ToolCallRecord
        even on failure — exceptions are captured, not raised."""
        start = time.monotonic()
        try:
            tool = self.registry.get(tool_name)
            result = tool.run(**args)
            duration = (time.monotonic() - start) * 1000
            return ToolCallRecord(
                tool_name=tool_name,
                args=args,
                result=result,
                duration_ms=round(duration, 2),
            )
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            logger.exception("Tool %s failed", tool_name)
            return ToolCallRecord(
                tool_name=tool_name,
                args=args,
                result={"error": str(exc)},
                duration_ms=round(duration, 2),
            )
