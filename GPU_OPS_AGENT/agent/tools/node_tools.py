"""Node-level tools — list_nodes, get_node_detail."""

from __future__ import annotations

from typing import Any

from models.domain import ScenarioRole
from models.snapshot import ClusterSnapshot
from services.snapshot_service import SnapshotService
from . import Tool


class ListNodes(Tool):
    name = "list_nodes"
    description = (
        "Return node list with lightweight fields (name, status, allocatable/available "
        "gpu/cpu/mem, labels).  Does NOT include pod-level detail — use get_node_detail "
        "for that.  Optionally filter by gpu_type, scenario, min_free_gpu."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "cluster_id": {"type": "string"},
            "gpu_type": {"type": "string"},
            "scenario": {"type": "string", "enum": ["Train", "Infer"]},
            "min_free_gpu": {"type": "integer", "description": "Minimum available GPU count"},
        },
        "required": ["cluster_id"],
    }

    def __init__(self, snapshot_service: SnapshotService) -> None:
        self._svc = snapshot_service

    def run(
        self,
        cluster_id: str,
        gpu_type: str | None = None,
        scenario: str | None = None,
        min_free_gpu: int | None = None,
    ) -> dict:
        snap = self._svc.get_current(cluster_id)
        nodes = snap.nodes

        if gpu_type:
            nodes = [n for n in nodes if n.gpu_type == gpu_type.lower()]
        if scenario:
            try:
                sr = ScenarioRole(scenario)
                nodes = [n for n in nodes if n.scenario == sr]
            except ValueError:
                pass
        if min_free_gpu is not None:
            nodes = [n for n in nodes if n.available.gpu >= min_free_gpu]

        return {
            "cluster_id": cluster_id,
            "node_count": len(nodes),
            "nodes": [
                {
                    "name": n.name,
                    "ip": n.ip,
                    "gpu_type": n.gpu_type,
                    "scenario": n.scenario.value,
                    "status": n.status.value,
                    "allocatable": {"gpu": n.allocatable.gpu, "cpu": n.allocatable.cpu, "mem": n.allocatable.mem},
                    "available": {"gpu": n.available.gpu, "cpu": n.available.cpu, "mem": n.available.mem},
                    "labels": n.labels,
                }
                for n in nodes
            ],
        }


class GetNodeDetail(Tool):
    name = "get_node_detail"
    description = (
        "Return full detail for a single node including GPUDistribution "
        "(pod-level GPU allocation)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "cluster_id": {"type": "string"},
            "node_name": {"type": "string"},
        },
        "required": ["cluster_id", "node_name"],
    }

    def __init__(self, snapshot_service: SnapshotService) -> None:
        self._svc = snapshot_service

    def run(self, cluster_id: str, node_name: str) -> dict:
        snap = self._svc.get_current(cluster_id)
        node = next((n for n in snap.nodes if n.name == node_name), None)
        if node is None:
            return {"error": f"Node {node_name!r} not found in cluster {cluster_id!r}"}

        return {
            "cluster_id": cluster_id,
            "node": {
                "name": node.name,
                "ip": node.ip,
                "gpu_type": node.gpu_type,
                "scenario": node.scenario.value,
                "status": node.status.value,
                "allocatable": {"gpu": node.allocatable.gpu, "cpu": node.allocatable.cpu, "mem": node.allocatable.mem},
                "available": {"gpu": node.available.gpu, "cpu": node.available.cpu, "mem": node.available.mem},
                "labels": node.labels,
                "taints": node.taints,
                "gpu_pod_count": len(node.pods),
                "gpu_distribution": [
                    {"pod_name": p.pod_name, "gpu_count": p.gpu_count}
                    for p in node.pods
                ],
            },
        }
