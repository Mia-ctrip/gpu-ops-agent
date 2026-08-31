"""Tests for SnapshotService against the *real* payload (data/demo.json).

Step 3 of the implementation order: manual ``refresh_now()`` + ``get_current()``
+ ring buffer, verified on real-shaped data without hitting the network.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from k8s_client import K8sApiError, K8sClient
from models.domain import ScenarioRole
from models.snapshot import ClusterSnapshot
from services.snapshot_service import SnapshotService

DEMO_JSON = "data/demo.json"

EXPECTED_NODE_COUNTS = {
    "AI-SHAXY-TCS-PRO1": 139,  # 40 train + 99 infer
    "SHARB-A": 225,
    "SHARE-SGP-ALI-PRO1": 385,
    "SHARE-SHA-ALI-PRO1": 1161,
    "SHAXY-B": 52,
}


@pytest.fixture
def real_snapshot_service(tmp_path: Path) -> SnapshotService:
    client = K8sClient(demo_data_path=DEMO_JSON)
    return SnapshotService(client, ring_buffer_size=3, snapshot_dir=tmp_path / "snapshots")


# ── Refresh / current ────────────────────────────────────────────────


def test_refresh_all_populates_every_cluster(real_snapshot_service: SnapshotService):
    real_snapshot_service.refresh_now()
    for cid, expected in EXPECTED_NODE_COUNTS.items():
        snap = real_snapshot_service.get_current(cid)
        assert snap.cluster_id == cid
        assert len(snap.nodes) == expected


def test_real_gpu_numbers_survive_the_whole_layer(real_snapshot_service: SnapshotService):
    real_snapshot_service.refresh_now()
    snap = real_snapshot_service.get_current("AI-SHAXY-TCS-PRO1")
    h20_train = [n for n in snap.nodes if n.gpu_type == "h20" and n.scenario == ScenarioRole.TRAIN]
    assert h20_train
    assert h20_train[0].allocatable.gpu == 8  # real Uppercase GPU key, not zeroed
    # allocatable >= available within a single node
    for n in snap.nodes:
        assert n.available.gpu <= n.allocatable.gpu


def test_single_cluster_refresh(real_snapshot_service: SnapshotService):
    real_snapshot_service.refresh_now("SHAXY-B")
    assert len(real_snapshot_service.get_current("SHAXY-B").nodes) == 52
    with pytest.raises(KeyError):
        real_snapshot_service.get_current("SHARB-A")  # not collected this round


def test_all_snapshots_share_one_collected_at(real_snapshot_service: SnapshotService):
    real_snapshot_service.refresh_now()
    stamps = {real_snapshot_service.get_current(cid).collected_at for cid in EXPECTED_NODE_COUNTS}
    assert len(stamps) == 1  # one poll round → one timestamp


def test_get_current_missing_cluster_raises(real_snapshot_service: SnapshotService):
    with pytest.raises(KeyError):
        real_snapshot_service.get_current("NONEXISTENT")


# ── Ring buffer / history ────────────────────────────────────────────


def test_ring_buffer_respects_maxlen(real_snapshot_service: SnapshotService):
    real_snapshot_service.refresh_now()
    real_snapshot_service.refresh_now()
    real_snapshot_service.refresh_now()
    real_snapshot_service.refresh_now()
    real_snapshot_service.refresh_now()
    history = real_snapshot_service.get_history("SHAXY-B")
    assert len(history) == 3  # ring_buffer_size
    assert history[-1].collected_at >= history[0].collected_at  # newest last
    for snap in history:
        assert len(snap.nodes) == 52  # all from the same real source


def test_get_history_limit(real_snapshot_service: SnapshotService):
    real_snapshot_service.refresh_now()
    real_snapshot_service.refresh_now()
    real_snapshot_service.refresh_now()
    assert len(real_snapshot_service.get_history("SHAXY-B", limit=2)) == 2
    assert real_snapshot_service.get_history("SHAXY-B", limit=0) == []


def test_get_history_limit_bounds(real_snapshot_service: SnapshotService):
    real_snapshot_service.refresh_now()
    real_snapshot_service.refresh_now()
    history = real_snapshot_service.get_history("SHAXY-B")
    assert real_snapshot_service.get_history("SHAXY-B", limit=10) == history
    assert real_snapshot_service.get_history("SHAXY-B") == history


# ── Failure tolerance ────────────────────────────────────────────────


def test_transient_api_failure_keeps_last_snapshot(monkeypatch, tmp_path: Path):
    with open(DEMO_JSON) as f:
        payload = json.load(f)
    state = {"fail": False}

    def fake_get(self, url, timeout):
        if state["fail"]:
            raise K8sApiError("simulated endpoint outage")
        return payload

    monkeypatch.setattr(K8sClient, "_http_get_json", fake_get)
    client = K8sClient()
    svc = SnapshotService(client, snapshot_dir=tmp_path / "snapshots")

    svc.refresh_now()
    assert len(svc.get_current("SHAXY-B").nodes) == 52

    state["fail"] = True
    svc.refresh_now()  # transient failure → keep last good snapshot, don't crash
    assert len(svc.get_current("SHAXY-B").nodes) == 52


def test_bad_node_is_skipped_not_fatal(monkeypatch, real_snapshot_service: SnapshotService):
    # corrupt exactly one node conversion; the cluster snapshot must survive
    calls = {"n": 0}
    real_convert = real_snapshot_service._k8s.raw_node_to_domain  # noqa: SLF001

    def flaky_convert(raw, cluster_id, scenario):
        calls["n"] += 1
        if calls["n"] == 7:
            raise ValueError("malformed node payload")
        return real_convert(raw, cluster_id, scenario)

    monkeypatch.setattr(real_snapshot_service._k8s, "raw_node_to_domain", flaky_convert)
    real_snapshot_service.refresh_now("AI-SHAXY-TCS-PRO1")  # 139 conversions this round
    snap = real_snapshot_service.get_current("AI-SHAXY-TCS-PRO1")
    assert calls["n"] == 139         # every node was attempted
    assert len(snap.nodes) == 138    # the corrupted one was skipped, not fatal


# ── Persistence ──────────────────────────────────────────────────────


def test_persist_writes_files_for_all_clusters(real_snapshot_service: SnapshotService, tmp_path: Path):
    real_snapshot_service.refresh_now()
    real_snapshot_service._persist_latest()  # noqa: SLF001

    for cid in EXPECTED_NODE_COUNTS:
        path = tmp_path / "snapshots" / f"{cid}.json"
        assert path.exists(), f"missing {cid}.json"
        data = json.loads(path.read_text())
        assert data["cluster_id"] == cid
        assert len(data["nodes"]) == EXPECTED_NODE_COUNTS[cid]
        # timestamps persisted in ISO format
        datetime.fromisoformat(data["collected_at"])
        first = data["nodes"][0]
        assert {"name", "ip", "gpu_type", "scenario", "status", "allocatable", "available"} <= set(first)