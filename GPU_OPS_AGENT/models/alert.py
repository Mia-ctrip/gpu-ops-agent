"""Alert model — produced by deterministic rule engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .domain import AlertSeverity, AlertType


@dataclass
class Alert:
    alert_id: str
    cluster_id: str
    type: AlertType
    severity: AlertSeverity
    node_name: str | None
    gpu_type: str | None
    message: str
    detected_at: datetime
    raw_values: dict = field(default_factory=dict)
