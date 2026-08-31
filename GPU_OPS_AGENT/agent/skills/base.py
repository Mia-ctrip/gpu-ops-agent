"""Skill base class — domain knowledge + allowed tools + output schema."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Skill(ABC):
    name: str
    instructions: str
    allowed_tools: list[str] = field(default_factory=list)
    output_schema: type | None = None

    def build_system_prompt(self) -> str:
        """Return the system prompt for the LLM when this skill is active."""
        parts = [
            f"# Skill: {self.name}",
            "",
            self.instructions,
            "",
            "## Constraints",
            "- All numerical data MUST come from tool results — never fabricate.",
            "- Always cite Evidence with exact field_path and value.",
            "- If information is insufficient, set confidence_note — do not guess.",
        ]
        return "\n".join(parts)
