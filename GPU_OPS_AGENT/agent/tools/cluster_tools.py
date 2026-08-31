"""Cluster-level tools — get_cluster_gpu_summary."""

from __future__ import annotations

from typing import Any

from models.domain import ScenarioRole
from models.snapshot import ClusterSnapshot
from services.snapshot_service import SnapshotService
from . import Tool


class GetClusterGpuSummary(Tool):
    name = "get_cluster_gpu_summary"
    description = (
        "Return total/used/free GPU counts, node counts, and ready/notready "
        "counts for a cluster.  Optionally filter by gpu_type and/or scenario."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "cluster_id": {"type": "string", "description": "Cluster identifier"},
            "gpu_type": {"type": "string", "description": "Filter by GPU type (e.g. h20, l20)"},
            "scenario": {
                "type": "string",
                "enum": ["Train", "Infer"],
                "description": "Filter by scenario",
            },
        },
        "required": ["cluster_id"],
    }

    def __init__(self, snapshot_service: SnapshotService) -> None:
        self._svc = snapshot_service

    def run(self, cluster_id: str, gpu_type: str | None = None, scenario: str | None = None) -> dict:
        snap = self._svc.get_current(cluster_id)
        nodes = _filter_nodes(snap, gpu_type=gpu_type, scenario=scenario)

        total_alloc = sum(n.allocatable.gpu for n in nodes)
        total_avail = sum(n.available.gpu for n in nodes)
        total_cpu_alloc = sum(n.allocatable.cpu for n in nodes)
        total_cpu_avail = sum(n.available.cpu for n in nodes)
        total_mem_alloc = sum(n.allocatable.mem for n in nodes)
        total_mem_avail = sum(n.available.mem for n in nodes)
        ready_count = sum(1 for n in nodes if n.status.value == "Ready")
        not_ready_count = sum(1 for n in nodes if n.status.value == "NotReady")

        return {
            "cluster_id": cluster_id,
            "filter": {"gpu_type": gpu_type, "scenario": scenario},
            "node_count": len(nodes),
            "ready_nodes": ready_count,
            "not_ready_nodes": not_ready_count,
            "total_allocatable_gpu": total_alloc,
            "total_available_gpu": total_avail,
            "total_used_gpu": total_alloc - total_avail,
            "total_allocatable_cpu": total_cpu_alloc,
            "total_available_cpu": total_cpu_avail,
            "total_allocatable_mem": total_mem_alloc,
            "total_available_mem": total_mem_avail,
        }


def _filter_nodes(
    snap: ClusterSnapshot,
    gpu_type: str | None = None,
    scenario: str | None = None,
) -> list:
    nodes = snap.nodes
    if gpu_type:
        nodes = [n for n in nodes if n.gpu_type == gpu_type.lower()]
    if scenario:
        try:
            sr = ScenarioRole(scenario)
            nodes = [n for n in nodes if n.scenario == sr]
        except ValueError:
            pass
    return nodes
