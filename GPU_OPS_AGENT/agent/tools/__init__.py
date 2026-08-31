"""Tool base class — a single read-only query capability."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Subclasses set name, description, input_schema as class attributes."""
    name: str = ""
    description: str = ""
    input_schema: dict = {}

    @abstractmethod
    def run(self, **kwargs: Any) -> dict:
        """Execute the tool.  Returns a JSON-serialisable dict."""
        ...
