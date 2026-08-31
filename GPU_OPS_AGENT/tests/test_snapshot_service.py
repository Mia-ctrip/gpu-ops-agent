"""Tests for SnapshotService."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from k8s_client import K8sClient
from models.domain import Node, NodeStatus, ResourceSpec, ScenarioRole
from models.snapshot import ClusterSnapshot
from services.snapshot_service import SnapshotService


# ── Fixtures ────────────────────────────────────────────────────────


def _make_demo_data() -> dict:
    return {
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
                                "GPUDistribution": {
                                    "pod-train-1": 3,
                                    "pod-train-2": 2,
                                },
                            },
                            {
                                "Name": "svr-02",
                                "Ip": "10.0.0.2",
                                "AcceleratorType": "nvidia-h20",
                                "Allocatable": {"gpu": 8, "cpu": 96, "mem": 1000000},
                                "Available": {"gpu": 8, "cpu": 96, "mem": 1000000},
                                "Status": "NotReady",
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
                                "GPUDistribution": {
                                    "r1000-infer-1": 2,
                                    "r1000-infer-2": 2,
                                },
                            },
                        ],
                    },
                }
            }
        }
    }


@pytest.fixture
def demo_file(tmp_path: Path) -> Path:
    data = _make_demo_data()
    p = tmp_path / "demo.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def snapshot_service(demo_file: Path, tmp_path: Path) -> SnapshotService:
    client = K8sClient(demo_data_path=demo_file)
    return SnapshotService(client, snapshot_dir=tmp_path / "snapshots")


# ── Tests ───────────────────────────────────────────────────────────


def test_refresh_populates_current(snapshot_service: SnapshotService):
    snapshot_service.refresh_now("TEST-CLUSTER")
    snap = snapshot_service.get_current("TEST-CLUSTER")

    assert snap.cluster_id == "TEST-CLUSTER"
    assert len(snap.nodes) == 3  # 2 Train + 1 Infer


def test_node_fields_correct(snapshot_service: SnapshotService):
    snapshot_service.refresh_now("TEST-CLUSTER")
    snap = snapshot_service.get_current("TEST-CLUSTER")

    svr01 = next(n for n in snap.nodes if n.name == "svr-01")
    assert svr01.gpu_type == "h20"
    assert svr01.scenario == ScenarioRole.TRAIN
    assert svr01.status == NodeStatus.READY
    assert svr01.allocatable.gpu == 8
    assert svr01.available.gpu == 3
    assert len(svr01.pods) == 2


def test_infer_scenario_parsed(snapshot_service: SnapshotService):
    snapshot_service.refresh_now("TEST-CLUSTER")
    snap = snapshot_service.get_current("TEST-CLUSTER")

    infer_nodes = [n for n in snap.nodes if n.scenario == ScenarioRole.INFER]
    assert len(infer_nodes) == 1
    assert infer_nodes[0].name == "vms-01"
    assert infer_nodes[0].gpu_type == "l20"


def test_history_ring_buffer(snapshot_service: SnapshotService):
    snapshot_service.refresh_now("TEST-CLUSTER")
    snapshot_service.refresh_now("TEST-CLUSTER")
    snapshot_service.refresh_now("TEST-CLUSTER")

    history = snapshot_service.get_history("TEST-CLUSTER")
    assert len(history) == 3


def test_get_current_missing_cluster_raises(snapshot_service: SnapshotService):
    with pytest.raises(KeyError):
        snapshot_service.get_current("NONEXISTENT")


def test_persist_writes_file(snapshot_service: SnapshotService, tmp_path: Path):
    snapshot_service.refresh_now("TEST-CLUSTER")
    snapshot_service._persist_latest()

    expected = tmp_path / "snapshots" / "TEST-CLUSTER.json"
    assert expected.exists()
    data = json.loads(expected.read_text())
    assert data["cluster_id"] == "TEST-CLUSTER"
    assert len(data["nodes"]) == 3
