"""Domain models — shared across the entire project, no business logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ScenarioRole(str, Enum):
    """K8s namespace / business scenario."""
    TRAIN = "Train"
    INFER = "Infer"


class NodeStatus(str, Enum):
    READY = "Ready"
    NOT_READY = "NotReady"


class AlertType(str, Enum):
    NODE_HEALTH = "NODE_HEALTH"
    GPU_REPORTING_ANOMALY = "GPU_REPORTING_ANOMALY"
    CAPACITY_WATERMARK = "CAPACITY_WATERMARK"


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class ResourceSpec:
    gpu: int = 0
    cpu: float = 0.0
    mem: float = 0.0  # bytes


@dataclass
class PodGpuAllocation:
    pod_name: str
    node_name: str
    gpu_count: int


@dataclass
class Node:
    name: str
    ip: str
    cluster_id: str
    gpu_type: str
    scenario: ScenarioRole
    status: NodeStatus
    allocatable: ResourceSpec = field(default_factory=ResourceSpec)
    available: ResourceSpec = field(default_factory=ResourceSpec)
    labels: dict = field(default_factory=dict)
    taints: list = field(default_factory=list)
    pods: list[PodGpuAllocation] = field(default_factory=list)
