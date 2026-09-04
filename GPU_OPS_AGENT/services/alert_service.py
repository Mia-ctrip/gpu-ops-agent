"""AlertService — deterministic rule engine.

Takes a ClusterSnapshot, returns a list of Alerts.
No LLM involvement — pure Python comparisons.

Three alert types:
1. NODE_HEALTH: Detects NotReady nodes
2. GPU_REPORTING_ANOMALY: Detects GPU reporting issues (two-stage: rule-based + statistical)
3. CAPACITY_WATERMARK: Detects high GPU watermark per GPU type (>90% CRITICAL, >75% WARNING)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Callable

from config import WATERMARK_CRITICAL, WATERMARK_WARNING, GPU_ANOMALY_RULES
from models.alert import Alert
from models.domain import AlertSeverity, AlertType, NodeStatus
from models.snapshot import ClusterSnapshot

logger = logging.getLogger(__name__)

# Type alias for a rule function
RuleFn = Callable[[ClusterSnapshot], list[Alert]]


class AlertService:
    def __init__(self) -> None:
        self.rules: list[RuleFn] = [
            _rule_node_health,
            _rule_gpu_reporting_anomaly,
            _rule_capacity_watermark,
        ]
        self._active: dict[str, list[Alert]] = {}  # Per-cluster dict

    def evaluate(self, snapshot: ClusterSnapshot) -> list[Alert]:
        """Run all rules against a snapshot, return new alerts."""
        alerts: list[Alert] = []
        for rule_fn in self.rules:
            try:
                alerts.extend(rule_fn(snapshot))
            except Exception:
                logger.exception("Rule %s failed", rule_fn.__name__)
        return alerts

    def get_active_alerts(self, cluster_id: str | None = None) -> list[Alert]:
        """Return most recent alert list, optionally filtered by cluster."""
        if cluster_id:
            return self._active.get(cluster_id, [])
        # Return alerts from all clusters
        all_alerts = []
        for alerts in self._active.values():
            all_alerts.extend(alerts)
        return all_alerts

    def refresh(self, snapshot: ClusterSnapshot) -> list[Alert]:
        """Evaluate and store as current active alerts for this cluster."""
        alerts = self.evaluate(snapshot)
        self._active[snapshot.cluster_id] = alerts
        return alerts


# ── Built-in rules ──────────────────────────────────────────────────


def _rule_node_health(snapshot: ClusterSnapshot) -> list[Alert]:
    """Alert on NotReady nodes.

    Rule: Node is NotReady → CRITICAL alert
    """
    alerts = []
    for node in snapshot.nodes:
        if node.status == NodeStatus.NOT_READY:
            alerts.append(Alert(
                alert_id=str(uuid.uuid4()),
                cluster_id=snapshot.cluster_id,
                type=AlertType.NODE_HEALTH,
                severity=AlertSeverity.CRITICAL,
                node_name=node.name,
                gpu_type=node.gpu_type,
                message=f"Node {node.name} is NotReady",
                detected_at=datetime.now(timezone.utc),
                raw_values={
                    "status": node.status.value,
                },
            ))
    return alerts


def _rule_gpu_reporting_anomaly(snapshot: ClusterSnapshot) -> list[Alert]:
    """Detect GPU reporting anomalies on each node.

    Two-stage detection (results merged with union):
    1. Rule-based: Absolute rules from operational experience
    2. Statistical: Frequency-based detection

    Only Allocatable GPU is checked; Available GPU is never used for anomaly detection.
    Available GPU can be any non-negative value - it's not used to determine anomalies.

    Data corruption checks (negative available, available > allocatable) are always performed.
    """
    alerts = []

    # Always check for data corruption first (independent of any rules)
    for node in snapshot.nodes:
        avail_gpu = node.available.gpu
        alloc_gpu = node.allocatable.gpu

        # Check for negative available GPU (impossible state)
        if avail_gpu < 0:
            alerts.append(Alert(
                alert_id=str(uuid.uuid4()),
                cluster_id=snapshot.cluster_id,
                type=AlertType.GPU_REPORTING_ANOMALY,
                severity=AlertSeverity.CRITICAL,
                node_name=node.name,
                gpu_type=node.gpu_type,
                message=f"Node {node.name} Available GPU={avail_gpu} is negative (data corruption detected)",
                detected_at=datetime.now(timezone.utc),
                raw_values={
                    "allocatable_gpu": alloc_gpu,
                    "available_gpu": avail_gpu,
                    "reason": "negative_available",
                },
            ))

        # Check for available > allocatable (critical anomaly)
        if avail_gpu > alloc_gpu:
            alerts.append(Alert(
                alert_id=str(uuid.uuid4()),
                cluster_id=snapshot.cluster_id,
                type=AlertType.GPU_REPORTING_ANOMALY,
                severity=AlertSeverity.CRITICAL,
                node_name=node.name,
                gpu_type=node.gpu_type,
                message=f"Node {node.name} Available GPU={avail_gpu} exceeds Allocatable GPU={alloc_gpu} (data corruption)",
                detected_at=datetime.now(timezone.utc),
                raw_values={
                    "allocatable_gpu": alloc_gpu,
                    "available_gpu": avail_gpu,
                    "reason": "available_exceeds_allocatable",
                },
            ))

    # Stage 1: Rule-based detection (absolute rules)
    alerts.extend(_detect_rule_based_anomalies(snapshot))

    # Stage 2: Statistical detection (frequency-based)
    alerts.extend(_detect_statistical_anomalies(snapshot))

    return alerts


def _detect_rule_based_anomalies(snapshot: ClusterSnapshot) -> list[Alert]:
    """Stage 1: Absolute rules based on operational experience.

    Use hard-coded rules for known cluster/gpu_type combinations.
    If a node's Allocatable GPU is in the anomalous set, flag it.

    Universal rule: Any non-CPU GPU type with Allocatable GPU = 0 is always anomalous.
    """
    alerts = []

    # Get rules for this cluster
    cluster_rules = GPU_ANOMALY_RULES.get(snapshot.cluster_id, {})

    for node in snapshot.nodes:
        alloc_gpu = node.allocatable.gpu
        gpu_type = node.gpu_type

        # Universal rule: Allocatable GPU = 0 for any non-CPU type is always anomalous
        if alloc_gpu == 0 and gpu_type.lower() not in ['cpu', 'coremodel']:
            alerts.append(Alert(
                alert_id=str(uuid.uuid4()),
                cluster_id=snapshot.cluster_id,
                type=AlertType.GPU_REPORTING_ANOMALY,
                severity=AlertSeverity.CRITICAL,
                node_name=node.name,
                gpu_type=gpu_type,
                message=f"Node {node.name} (type {gpu_type}) Allocatable GPU=0 (GPU type should have GPUs)",
                detected_at=datetime.now(timezone.utc),
                raw_values={
                    "allocatable_gpu": alloc_gpu,
                    "gpu_type": gpu_type,
                    "reason": "zero_allocatable_gpu",
                },
            ))
            continue  # Skip cluster-specific rules for this node

        # Check if this gpu_type has cluster-specific rules
        if gpu_type in cluster_rules:
            anomalous_counts = cluster_rules[gpu_type]

            # If allocatable GPU is in the anomalous set, report it
            if alloc_gpu in anomalous_counts:
                alerts.append(Alert(
                    alert_id=str(uuid.uuid4()),
                    cluster_id=snapshot.cluster_id,
                    type=AlertType.GPU_REPORTING_ANOMALY,
                    severity=AlertSeverity.WARNING,
                    node_name=node.name,
                    gpu_type=gpu_type,
                    message=f"Node {node.name} (type {gpu_type}) Allocatable GPU={alloc_gpu} violates cluster rule",
                    detected_at=datetime.now(timezone.utc),
                    raw_values={
                        "allocatable_gpu": alloc_gpu,
                        "gpu_type": gpu_type,
                        "anomalous_values": sorted(anomalous_counts),
                        "reason": "rule_based_anomaly",
                    },
                ))

    return alerts


def _detect_statistical_anomalies(snapshot: ClusterSnapshot) -> list[Alert]:
    """Stage 2: Statistical detection - frequency-based anomalies.

    For GPU types without hard rules (or as a second opinion),
    detect values that never appear in the cluster for that type.
    """
    alerts = []

    # Collect frequency statistics per GPU TYPE (excluding CPU/coreModel)
    gpu_type_alloc_counts: dict[str, dict[int, int]] = {}

    for node in snapshot.nodes:
        gpu_type = node.gpu_type

        # Skip CPU/coreModel nodes from frequency analysis
        if gpu_type.lower() in ['cpu', 'coremodel']:
            continue

        alloc_gpu = node.allocatable.gpu

        if gpu_type not in gpu_type_alloc_counts:
            gpu_type_alloc_counts[gpu_type] = {}

        if alloc_gpu not in gpu_type_alloc_counts[gpu_type]:
            gpu_type_alloc_counts[gpu_type][alloc_gpu] = 0

        gpu_type_alloc_counts[gpu_type][alloc_gpu] += 1

    # Build valid count sets for each GPU type
    gpu_type_valid_counts: dict[str, set] = {}
    for gpu_type, alloc_counts in gpu_type_alloc_counts.items():
        if alloc_counts:
            gpu_type_valid_counts[gpu_type] = set(alloc_counts.keys())

    # Check each node for statistical anomalies
    for node in snapshot.nodes:
        alloc_gpu = node.allocatable.gpu
        gpu_type = node.gpu_type

        # Skip CPU/coreModel nodes
        if gpu_type.lower() not in ['cpu', 'coremodel']:
            valid_counts_for_type = gpu_type_valid_counts.get(gpu_type, set())

            # Only flag if:
            # - This GPU type has >1 distinct count in the cluster (variation exists)
            # - Valid counts set is not empty
            # - Node's allocatable GPU is > 0
            # - Node's allocatable GPU is NOT in the valid set (never seen for this type)
            if len(gpu_type_alloc_counts.get(gpu_type, {})) > 1 and valid_counts_for_type:
                if alloc_gpu > 0 and alloc_gpu not in valid_counts_for_type:
                    alerts.append(Alert(
                        alert_id=str(uuid.uuid4()),
                        cluster_id=snapshot.cluster_id,
                        type=AlertType.GPU_REPORTING_ANOMALY,
                        severity=AlertSeverity.CRITICAL,
                        node_name=node.name,
                        gpu_type=node.gpu_type,
                        message=f"Node {node.name} (type {gpu_type}) Allocatable GPU={alloc_gpu} not found in cluster distribution {sorted(valid_counts_for_type)}",
                        detected_at=datetime.now(timezone.utc),
                        raw_values={
                            "allocatable_gpu": alloc_gpu,
                            "gpu_type": gpu_type,
                            "valid_gpu_counts": sorted(valid_counts_for_type),
                            "reason": "statistical_anomaly",
                        },
                    ))

    return alerts


def _rule_capacity_watermark(snapshot: ClusterSnapshot) -> list[Alert]:
    """Alert on high GPU capacity watermark per GPU type.

    Rules:
    1. For each GPU type (excluding 'cpu'), calculate: utilization = (total_allocatable - total_available) / total_allocatable
    2. If utilization >= 100% → CRITICAL alert (red) - data corruption or oversubscription
    3. If 75% <= utilization < 100% → WARNING alert (yellow) - approaching limits
    4. Below 75% → no alert

    Returns one alert per GPU type per severity level.
    """
    alerts = []

    # Group nodes by GPU type
    gpu_type_nodes: dict[str, list] = {}
    for node in snapshot.nodes:
        # Only consider Ready nodes and skip CPU type
        if node.status != NodeStatus.READY or node.gpu_type == "cpu":
            continue
        if node.gpu_type not in gpu_type_nodes:
            gpu_type_nodes[node.gpu_type] = []
        gpu_type_nodes[node.gpu_type].append(node)

    # Calculate watermark for each GPU type
    for gpu_type, nodes in gpu_type_nodes.items():
        total_alloc = sum(n.allocatable.gpu for n in nodes)
        total_avail = sum(n.available.gpu for n in nodes)

        if total_alloc == 0:
            continue  # Skip if no GPUs allocated

        utilization = (total_alloc - total_avail) / total_alloc

        # Generate appropriate alert based on utilization level
        if utilization >= 1.0:  # >= 100% - CRITICAL
            alerts.append(Alert(
                alert_id=str(uuid.uuid4()),
                cluster_id=snapshot.cluster_id,
                type=AlertType.CAPACITY_WATERMARK,
                severity=AlertSeverity.CRITICAL,
                node_name=None,
                gpu_type=gpu_type,
                message=f"GPU type '{gpu_type}' utilization at {utilization:.1%} (oversubscribed - available GPU is negative)",
                detected_at=datetime.now(timezone.utc),
                raw_values={
                    "gpu_type": gpu_type,
                    "node_count": len(nodes),
                    "total_allocatable": total_alloc,
                    "total_available": total_avail,
                    "total_used": total_alloc - total_avail,
                    "utilization_ratio": round(utilization, 4),
                    "affected_nodes": [n.name for n in nodes],
                },
            ))
        elif utilization >= WATERMARK_WARNING:  # >= 75% - WARNING
            alerts.append(Alert(
                alert_id=str(uuid.uuid4()),
                cluster_id=snapshot.cluster_id,
                type=AlertType.CAPACITY_WATERMARK,
                severity=AlertSeverity.WARNING,
                node_name=None,
                gpu_type=gpu_type,
                message=f"GPU type '{gpu_type}' utilization at {utilization:.1%} (approaching capacity limit)",
                detected_at=datetime.now(timezone.utc),
                raw_values={
                    "gpu_type": gpu_type,
                    "node_count": len(nodes),
                    "total_allocatable": total_alloc,
                    "total_available": total_avail,
                    "total_used": total_alloc - total_avail,
                    "utilization_ratio": round(utilization, 4),
                    "affected_nodes": [n.name for n in nodes],
                },
            ))

    return alerts
