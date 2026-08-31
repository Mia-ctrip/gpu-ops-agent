"""Tests for dashboard routes, primarily /clusters/{id}/facts.

Route functions are plain Python, so we exercise them directly (no TestClient
/httpx dependency).  Services are initialised over the *real* data/demo.json
through SnapshotService; numbers below are exact aggregates of that file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from k8s_client import K8sClient
from services.alert_service import AlertService
from services.snapshot_service import SnapshotService

import api.dashboard_routes as routes

DEMO_JSON = "data/demo.json"

# Exact aggregates captured from data/demo.json
# Only counts Ready nodes for GPU summary (3 NotReady nodes excluded)
AI_SHAXY_REDUCED = {
    "node_count": 136,  # Ready nodes only
    "gpu_total": 1072,  # Ready nodes only
    "gpu_available": 71,  # from Ready nodes only (NotReady has 10 more)
    "gpu_used": 1001,  # 1072 - 71 (Ready only)
    "ready_nodes": 136,
    "not_ready_nodes": 3,
}
SHA_ALI_TOTAL_GPU = 2004  # Updated for Ready nodes only


@pytest.fixture(scope="module")
def real_facts() -> dict:
    svc = SnapshotService(K8sClient(demo_data_path=DEMO_JSON))
    svc.refresh_now()
    alert_svc = AlertService()
    routes.init_services(svc, alert_svc)
    return routes.get_cluster_facts("AI-SHAXY-TCS-PRO1")


@pytest.fixture(scope="module")
def all_facts() -> dict:
    svc = SnapshotService(K8sClient(demo_data_path=DEMO_JSON))
    svc.refresh_now()
    routes.init_services(svc, AlertService())
    return {
        cid: routes.get_cluster_facts(cid)
        for cid in ("AI-SHAXY-TCS-PRO1", "SHARB-A", "SHARE-SGP-ALI-PRO1", "SHARE-SHA-ALI-PRO1", "SHAXY-B")
    }


# ── Headline scalars ────────────────────────────────────────────────


def test_facts_headline_numbers(real_facts: dict):
    for key, expected in AI_SHAXY_REDUCED.items():
        assert real_facts[key] == expected, f"{key}: {real_facts[key]} != {expected}"
    assert real_facts["cluster_id"] == "AI-SHAXY-TCS-PRO1"
    assert real_facts["collected_at"].endswith("+00:00")
    assert len(real_facts["not_ready_nodes_list"]) == 3
    assert "utilization_percent" in real_facts



def test_facts_labels_are_object_fields_not_dict_keys(real_facts: dict):
    """Breakdowns are lists of objects with explicit label fields."""
    for group in real_facts["by_gpu_type"]:
        assert isinstance(group["gpu_type"], str) and "gpu_type" in group
        assert group["gpu_type"] != ""  # never a bare dict key
    for scenario in real_facts["by_scenario"]:
        assert scenario["scenario"] in ("Train", "Infer")


def test_facts_by_gpu_type(real_facts: dict):
    by_type = {g["gpu_type"]: g for g in real_facts["by_gpu_type"]}
    # CPU type should be filtered out
    assert set(by_type) == {"h20", "h20-141", "h200", "l20"}
    # h20: 65 Ready nodes, 520 GPUs
    assert by_type["h20"]["node_count"] == 65
    assert by_type["h20"]["allocatable_gpu"] == 520
    # h20-141: 32 Ready nodes, 256 GPUs
    assert by_type["h20-141"]["node_count"] == 32
    assert by_type["h20-141"]["allocatable_gpu"] == 256
    # All should have utilization_percent
    for gpu_type, group in by_type.items():
        assert "utilization_percent" in group
        assert group["allocatable_gpu"] == group["used_gpu"] + group["available_gpu"]
    # Total node count excluding cpu nodes
    assert sum(g["node_count"] for g in real_facts["by_gpu_type"]) == 135


def test_facts_by_scenario(real_facts: dict):
    by_scen = {s["scenario"]: s for s in real_facts["by_scenario"]}
    # Ready nodes only: Train=39, Infer=97
    assert by_scen["Train"]["node_count"] == 39
    assert by_scen["Infer"]["node_count"] == 97
    assert sum(s["node_count"] for s in real_facts["by_scenario"]) == 136


def test_facts_numbers_are_internally_consistent(real_facts: dict):
    # gpu used/available must sum to total everywhere it is computed
    assert real_facts["gpu_total"] == real_facts["gpu_used"] + real_facts["gpu_available"]
    assert sum(g["allocatable_gpu"] for g in real_facts["by_gpu_type"]) == real_facts["gpu_total"]
    assert sum(g["allocatable_gpu"] for g in real_facts["by_scenario"]) == real_facts["gpu_total"]
    # New flat node structure: allocatable_gpu, available_gpu
    assert sum(n["allocatable_gpu"] for n in real_facts["nodes"]) == real_facts["gpu_total"]
    assert sum(n["available_gpu"] for n in real_facts["nodes"]) == real_facts["gpu_available"]


# ── Per-node summary ────────────────────────────────────────────────


def test_facts_node_summary_shape(real_facts: dict):
    required = {"name", "ip", "gpu_type", "scenario", "status", "allocatable_gpu", "available_gpu", "gpu_pod_count"}
    for node in real_facts["nodes"]:
        assert required <= set(node), f"Node missing fields: {required - set(node)}"
        assert node["status"] == "Ready"  # Only Ready nodes in summary
        assert node["gpu_pod_count"] >= 0


def test_facts_all_clusters(real_facts: dict, all_facts: dict):
    assert len(all_facts) == 5
    assert all_facts["SHAXY-B"]["node_count"] == 51  # Ready nodes only
    assert all_facts["SHAXY-B"]["gpu_total"] == 121
    assert all_facts["SHARE-SHA-ALI-PRO1"]["gpu_total"] == SHA_ALI_TOTAL_GPU
    # every cluster's by_gpu_type conserves GPU totals (cpu nodes are filtered out)
    for cluster_id, facts in all_facts.items():
        total_gpu_by_type = sum(g["allocatable_gpu"] for g in facts["by_gpu_type"])
        assert total_gpu_by_type == facts["gpu_total"], f"{cluster_id}: GPU mismatch"


# ── Error handling ──────────────────────────────────────────────────


def test_facts_unknown_cluster_404(all_facts: dict):
    with pytest.raises(HTTPException) as exc:
        routes.get_cluster_facts("NONEXISTENT")
    assert exc.value.status_code == 404


def test_facts_uninitialised_service_503(monkeypatch):
    monkeypatch.setattr(routes, "_snapshot_service", None)
    with pytest.raises(HTTPException) as exc:
        routes.get_cluster_facts("AI-SHAXY-TCS-PRO1")
    assert exc.value.status_code == 503


# ── Sibling endpoints (sanity) ──────────────────────────────────────


def test_list_clusters():
    clusters = routes.list_clusters()["clusters"]
    assert clusters == ["AI-SHAXY-TCS-PRO1", "SHARB-A", "SHARE-SGP-ALI-PRO1", "SHARE-SHA-ALI-PRO1", "SHAXY-B"]


def test_trend_endpoint(real_facts: dict):
    # refresh twice via a fresh service so history has at least 2 points
    svc = SnapshotService(K8sClient(demo_data_path=DEMO_JSON))
    svc.refresh_now("AI-SHAXY-TCS-PRO1")
    svc.refresh_now("AI-SHAXY-TCS-PRO1")
    routes.init_services(svc, AlertService())

    trend = routes.get_cluster_trend("AI-SHAXY-TCS-PRO1", limit=50)

    # Check structure
    assert "cluster_id" in trend
    assert "by_gpu_type" in trend
    assert isinstance(trend["by_gpu_type"], dict)

    # Should have multiple GPU types (h20, l20, h20-141, h200)
    assert len(trend["by_gpu_type"]) >= 4

    # Each GPU type should have at least 2 data points
    for gpu_type, data_points in trend["by_gpu_type"].items():
        assert len(data_points) >= 2, f"GPU type {gpu_type} has {len(data_points)} data points, expected >= 2"
        assert "collected_at" in data_points[0]
        assert "allocatable_gpu" in data_points[0]
        assert "available_gpu" in data_points[0]
        assert "used_gpu" in data_points[0]

    # Test filtering by gpu_type
    trend_h20 = routes.get_cluster_trend("AI-SHAXY-TCS-PRO1", limit=50, gpu_type="h20")
    assert len(trend_h20["by_gpu_type"]) == 1
    assert "h20" in trend_h20["by_gpu_type"]