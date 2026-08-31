"""Agent output models — contract between Agent and UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCallRecord:
    tool_name: str
    args: dict
    result: Any
    duration_ms: float


@dataclass
class Evidence:
    source: str  # e.g. "snapshot_service.get_current" / tool name
    cluster_id: str
    node_name: str | None
    field_path: str  # e.g. "nodes[svr-01].available.gpu"
    value: Any  # real value — LLM must not fabricate


@dataclass
class Recommendation:
    rank: int  # 1 = best, 2/3 = alternatives
    action_summary: str
    affected_nodes: list[str] = field(default_factory=list)
    affected_pods: list[str] = field(default_factory=list)
    estimated_impact: str = ""
    caveats: str | None = None


@dataclass
class AgentDecision:
    session_id: str
    skill_used: str
    diagnosis: str
    evidence: list[Evidence] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)
    alternatives_considered: str | None = None
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    confidence_note: str | None = None
