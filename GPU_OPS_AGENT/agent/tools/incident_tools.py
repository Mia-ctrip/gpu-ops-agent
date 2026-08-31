"""Incident-related tools — get_pod_gpu_allocation, get_active_alerts, get_service_owner (stub)."""

from __future__ import annotations

from typing import Any

from services.alert_service import AlertService
from services.snapshot_service import SnapshotService
from . import Tool


class GetPodGpuAllocation(Tool):
    name = "get_pod_gpu_allocation"
    description = (
        "Return pod-level GPU allocation.  Optionally filter by node_name or pod_name. "
        "Can search across all nodes when neither is given."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "cluster_id": {"type": "string"},
            "node_name": {"type": "string", "description": "Filter by node"},
            "pod_name": {"type": "string", "description": "Filter by pod name (substring match)"},
        },
        "required": ["cluster_id"],
    }

    def __init__(self, snapshot_service: SnapshotService) -> None:
        self._svc = snapshot_service

    def run(
        self,
        cluster_id: str,
        node_name: str | None = None,
        pod_name: str | None = None,
    ) -> dict:
        snap = self._svc.get_current(cluster_id)
        allocations: list[dict] = []

        for node in snap.nodes:
            if node_name and node.name != node_name:
                continue
            for pod in node.pods:
                if pod_name and pod_name.lower() not in pod.pod_name.lower():
                    continue
                allocations.append({
                    "pod_name": pod.pod_name,
                    "node_name": pod.node_name,
                    "gpu_count": pod.gpu_count,
                    "node_gpu_type": node.gpu_type,
                    "node_status": node.status.value,
                })

        return {
            "cluster_id": cluster_id,
            "total_pods": len(allocations),
            "allocations": allocations,
        }


class GetActiveAlerts(Tool):
    name = "get_active_alerts"
    description = (
        "Return the current list of deterministic alerts.  "
        "Use this before reasoning about node health or GPU anomalies — "
        "the AlertService has already computed them."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "cluster_id": {"type": "string", "description": "Filter by cluster (optional)"},
        },
    }

    def __init__(self, alert_service: AlertService) -> None:
        self._alert_svc = alert_service

    def run(self, cluster_id: str | None = None) -> dict:
        alerts = self._alert_svc.get_active_alerts(cluster_id)
        return {
            "alert_count": len(alerts),
            "alerts": [
                {
                    "alert_id": a.alert_id,
                    "cluster_id": a.cluster_id,
                    "type": a.type.value,
                    "severity": a.severity.value,
                    "node_name": a.node_name,
                    "gpu_type": a.gpu_type,
                    "message": a.message,
                    "detected_at": a.detected_at.isoformat(),
                    "raw_values": a.raw_values,
                }
                for a in alerts
            ],
        }


class GetServiceOwner(Tool):
    name = "get_service_owner"
    description = (
        "Return service metadata (name, owner, contact) for a given pod.  "
        "Currently a STUB — returns NotImplemented."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pod_name": {"type": "string"},
        },
        "required": ["pod_name"],
    }

    def run(self, pod_name: str) -> dict:
        return {
            "status": "NotImplemented",
            "message": "Service metadata system not yet integrated",
            "pod_name": pod_name,
        }
