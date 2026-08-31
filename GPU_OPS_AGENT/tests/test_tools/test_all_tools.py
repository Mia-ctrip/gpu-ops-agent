"""Tests for agent tools — cluster_tools, node_tools, incident_tools."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from k8s_client import K8sClient
from models.domain import ScenarioRole
from services.alert_service import AlertService
from services.snapshot_service import SnapshotService
from agent.tools.cluster_tools import GetClusterGpuSummary
from agent.tools.node_tools import ListNodes, GetNodeDetail
from agent.tools.incident_tools import GetPodGpuAllocation, GetActiveAlerts, GetServiceOwner


# ── Fixtures ────────────────────────────────────────────────────────


DEMO_DATA = {
    "Clusters": {
        "TEST-CLUSTER": {
            "Data": {
                "Train": {
                    "nvidia-h20": [
                        {
                            "Name": "svr-01",
                            "Ip": "10.0.0.1",
                            "AcceleratorType": "nvidia-h20",
                            "Allocatable": {"gpu": 8, "cpu": 96, "mem": 1000000},
                            "Available": {"gpu": 3, "cpu": 48, "mem": 500000},
                            "Status": "Ready",
                            "GPUPodCount": 3,
                            "GPUDistribution": {"pod-a": 3, "pod-b": 2},
                        },
                        {
                            "Name": "svr-02",
                            "Ip": "10.0.0.2",
                            "AcceleratorType": "nvidia-h20",
                            "Allocatable": {"gpu": 8, "cpu": 96, "mem": 1000000},
                            "Available": {"gpu": 8, "cpu": 96, "mem": 1000000},
                            "Status": "Ready",
                            "GPUPodCount": 0,
                            "GPUDistribution": {},
                        },
                    ],
                },
                "Infer": {
                    "nvidia-l20": [
                        {
                            "Name": "vms-01",
                            "Ip": "10.0.1.1",
                            "AcceleratorType": "nvidia-tesla-l20-4-192",
                            "Allocatable": {"gpu": 4, "cpu": 48, "mem": 500000},
                            "Available": {"gpu": 0, "cpu": 12, "mem": 100000},
                            "Status": "Ready",
                            "GPUPodCount": 2,
                            "GPUDistribution": {"r1000-infer-1": 2, "r1000-infer-2": 2},
                        },
                    ],
                },
            }
        }
    }
}


@pytest.fixture
def services(tmp_path: Path) -> tuple[SnapshotService, AlertService]:
    demo_file = tmp_path / "demo.json"
    demo_file.write_text(json.dumps(DEMO_DATA))
    client = K8sClient(demo_data_path=demo_file)
    svc = SnapshotService(client)
    svc.refresh_now("TEST-CLUSTER")
    alert_svc = AlertService()
    alert_svc.refresh(svc.get_current("TEST-CLUSTER"))
    return svc, alert_svc


# ── GetClusterGpuSummary ────────────────────────────────────────────


class TestGetClusterGpuSummary:
    def test_total_summary(self, services):
        svc, _ = services
        tool = GetClusterGpuSummary(svc)
        result = tool.run(cluster_id="TEST-CLUSTER")

        assert result["node_count"] == 3
        assert result["total_allocatable_gpu"] == 20  # 8+8+4
        assert result["total_available_gpu"] == 11     # 3+8+0
        assert result["total_used_gpu"] == 9

    def test_filter_by_gpu_type(self, services):
        svc, _ = services
        tool = GetClusterGpuSummary(svc)
        result = tool.run(cluster_id="TEST-CLUSTER", gpu_type="h20")

        assert result["node_count"] == 2
        assert result["total_allocatable_gpu"] == 16  # 8+8

    def test_filter_by_scenario(self, services):
        svc, _ = services
        tool = GetClusterGpuSummary(svc)
        result = tool.run(cluster_id="TEST-CLUSTER", scenario="Infer")

        assert result["node_count"] == 1
        assert result["total_allocatable_gpu"] == 4


# ── ListNodes ──────────────────────────────────────────────────────


class TestListNodes:
    def test_list_all(self, services):
        svc, _ = services
        tool = ListNodes(svc)
        result = tool.run(cluster_id="TEST-CLUSTER")

        assert result["node_count"] == 3
        names = {n["name"] for n in result["nodes"]}
        assert names == {"svr-01", "svr-02", "vms-01"}

    def test_filter_min_free_gpu(self, services):
        svc, _ = services
        tool = ListNodes(svc)
        result = tool.run(cluster_id="TEST-CLUSTER", min_free_gpu=8)

        assert result["node_count"] == 1
        assert result["nodes"][0]["name"] == "svr-02"

    def test_no_pod_detail_in_list(self, services):
        """list_nodes should NOT include pod-level detail."""
        svc, _ = services
        tool = ListNodes(svc)
        result = tool.run(cluster_id="TEST-CLUSTER")

        for node in result["nodes"]:
            assert "gpu_distribution" not in node
            assert "pods" not in node


# ── GetNodeDetail ──────────────────────────────────────────────────


class TestGetNodeDetail:
    def test_existing_node(self, services):
        svc, _ = services
        tool = GetNodeDetail(svc)
        result = tool.run(cluster_id="TEST-CLUSTER", node_name="svr-01")

        node = result["node"]
        assert node["name"] == "svr-01"
        assert node["gpu_pod_count"] == 2
        assert len(node["gpu_distribution"]) == 2

    def test_missing_node(self, services):
        svc, _ = services
        tool = GetNodeDetail(svc)
        result = tool.run(cluster_id="TEST-CLUSTER", node_name="nonexistent")

        assert "error" in result


# ── GetPodGpuAllocation ────────────────────────────────────────────


class TestGetPodGpuAllocation:
    def test_all_pods(self, services):
        svc, _ = services
        tool = GetPodGpuAllocation(svc)
        result = tool.run(cluster_id="TEST-CLUSTER")

        assert result["total_pods"] == 4  # 2+0+2

    def test_filter_by_node(self, services):
        svc, _ = services
        tool = GetPodGpuAllocation(svc)
        result = tool.run(cluster_id="TEST-CLUSTER", node_name="svr-01")

        assert result["total_pods"] == 2

    def test_filter_by_pod_name(self, services):
        svc, _ = services
        tool = GetPodGpuAllocation(svc)
        result = tool.run(cluster_id="TEST-CLUSTER", pod_name="r1000")

        assert result["total_pods"] == 2
        for alloc in result["allocations"]:
            assert "r1000" in alloc["pod_name"]


# ── GetActiveAlerts ────────────────────────────────────────────────


class TestGetActiveAlerts:
    def test_returns_alerts(self, services):
        _, alert_svc = services
        tool = GetActiveAlerts(alert_svc)
        result = tool.run()

        # Our test data has all Ready nodes with valid GPU counts,
        # so should have 0 alerts (unless watermark triggers)
        assert "alert_count" in result
        assert "alerts" in result


# ── GetServiceOwner (stub) ─────────────────────────────────────────


class TestGetServiceOwner:
    def test_returns_not_implemented(self):
        tool = GetServiceOwner()
        result = tool.run(pod_name="test-pod")

        assert result["status"] == "NotImplemented"
