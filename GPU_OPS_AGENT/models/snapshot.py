"""Snapshot models — point-in-time cluster state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .domain import Node


@dataclass
class ClusterSnapshot:
    cluster_id: str
    collected_at: datetime
    nodes: list[Node] = field(default_factory=list)
