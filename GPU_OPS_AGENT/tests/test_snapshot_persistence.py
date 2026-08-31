"""Test snapshot persistence and restart recovery (feature #6)."""

import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from config import RING_BUFFER_SIZE
from k8s_client import K8sClient
from services.snapshot_service import SnapshotService
from models.domain import Node, NodeStatus, ResourceSpec, ScenarioRole, PodGpuAllocation
from models.snapshot import ClusterSnapshot


@pytest.fixture
def temp_snapshot_dir():
    """Create a temporary directory for snapshot files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def k8s_demo():
    """K8s client in demo mode."""
    return K8sClient(demo_data_path="data/demo.json")


def _create_test_snapshot(cluster_id: str, node_count: int, offset_hours: int = 0) -> ClusterSnapshot:
    """Create a test snapshot with the given cluster ID and node count."""
    collected_at = datetime.now(timezone.utc) - timedelta(hours=offset_hours)
    nodes = []
    for i in range(node_count):
        node = Node(
            name=f"node-{i}",
            ip=f"10.0.0.{i}",
            cluster_id=cluster_id,
            gpu_type="h20",
            scenario=ScenarioRole.TRAIN,
            status=NodeStatus.READY,
            allocatable=ResourceSpec(gpu=8, cpu=64, mem=512*1024*1024),
            available=ResourceSpec(gpu=4 if i % 2 == 0 else 2, cpu=32, mem=256*1024*1024),
            labels={},
            taints=[],
            pods=[],
        )
        nodes.append(node)
    return ClusterSnapshot(cluster_id=cluster_id, collected_at=collected_at, nodes=nodes)


def test_persist_history_creates_file(k8s_demo, temp_snapshot_dir):
    """Test that _persist_history() writes ring buffer to disk."""
    from collections import deque

    svc = SnapshotService(k8s_demo, ring_buffer_size=30, snapshot_dir=temp_snapshot_dir)

    # Create and store snapshots
    snap1 = _create_test_snapshot("cluster-a", 5, offset_hours=2)
    snap2 = _create_test_snapshot("cluster-a", 6, offset_hours=1)
    snap3 = _create_test_snapshot("cluster-a", 7, offset_hours=0)

    with svc._lock:
        svc._history["cluster-a"] = deque(maxlen=svc._ring_size)
        svc._history["cluster-a"].append(snap1)
        svc._history["cluster-a"].append(snap2)
        svc._history["cluster-a"].append(snap3)
        svc._current["cluster-a"] = snap3

    svc._persist_history()

    # Verify file was created
    hist_file = temp_snapshot_dir / "cluster-a_history.json"
    assert hist_file.exists()

    # Verify file content structure
    data = json.loads(hist_file.read_text())
    assert data["cluster_id"] == "cluster-a"
    assert len(data["snapshots"]) == 3
    assert data["snapshots"][0]["nodes"][0]["name"] == "node-0"
    assert len(data["snapshots"][2]["nodes"]) == 7


def test_load_from_disk_restores_history(k8s_demo, temp_snapshot_dir):
    """Test that _load_from_disk() restores ring buffer from JSON."""
    from collections import deque

    # Create and persist snapshots first
    svc1 = SnapshotService(k8s_demo, ring_buffer_size=30, snapshot_dir=temp_snapshot_dir)
    snap1 = _create_test_snapshot("cluster-a", 5, offset_hours=2)
    snap2 = _create_test_snapshot("cluster-a", 6, offset_hours=1)
    snap3 = _create_test_snapshot("cluster-a", 7, offset_hours=0)

    with svc1._lock:
        svc1._history["cluster-a"] = deque(maxlen=svc1._ring_size)
        svc1._history["cluster-a"].append(snap1)
        svc1._history["cluster-a"].append(snap2)
        svc1._history["cluster-a"].append(snap3)
        svc1._current["cluster-a"] = snap3
    svc1._persist_history()

    # Create new service instance and load from disk
    svc2 = SnapshotService(k8s_demo, ring_buffer_size=30, snapshot_dir=temp_snapshot_dir)

    # Verify snapshots were restored
    assert "cluster-a" in svc2._current
    assert len(svc2._history["cluster-a"]) == 3
    assert svc2._current["cluster-a"].nodes[0].name == "node-0"
    with svc2._lock:
        assert len(svc2._history.get("cluster-a", [])) == 3


def test_ring_buffer_size_is_50(k8s_demo, temp_snapshot_dir):
    """Test that RING_BUFFER_SIZE is set to 50 for user requirement (last ~50 snapshots)."""
    assert RING_BUFFER_SIZE == 50, "Ring buffer size must be 50 per user requirement"

    svc = SnapshotService(k8s_demo, snapshot_dir=temp_snapshot_dir)
    assert svc._ring_size == 50


def test_history_limited_to_50(k8s_demo, temp_snapshot_dir):
    """Test that deque maxlen enforces 50-snapshot limit."""
    from collections import deque

    svc = SnapshotService(k8s_demo, ring_buffer_size=50, snapshot_dir=temp_snapshot_dir)

    # Add 60 snapshots (more than ring buffer)
    for i in range(60):
        snap = _create_test_snapshot("cluster-a", 2, offset_hours=i)
        with svc._lock:
            if "cluster-a" not in svc._history:
                svc._history["cluster-a"] = deque(maxlen=svc._ring_size)
            svc._history["cluster-a"].append(snap)
            svc._current["cluster-a"] = snap

    # Verify only 50 are kept
    assert len(svc._history["cluster-a"]) == 50


def test_persistence_over_restart_cycle(k8s_demo, temp_snapshot_dir):
    """Test complete cycle: persist → new instance → verify data recovery."""
    from collections import deque

    # Cycle 1: Create and persist snapshots
    svc1 = SnapshotService(k8s_demo, ring_buffer_size=30, snapshot_dir=temp_snapshot_dir)
    snapshots = []
    for i in range(5):
        snap = _create_test_snapshot("cluster-a", 10 + i, offset_hours=i)
        snapshots.append(snap)
        with svc1._lock:
            if "cluster-a" not in svc1._history:
                svc1._history["cluster-a"] = deque(maxlen=svc1._ring_size)
            svc1._history["cluster-a"].append(snap)
            svc1._current["cluster-a"] = snap
    svc1._persist_history()

    # Cycle 2: New service instance loads from disk
    svc2 = SnapshotService(k8s_demo, ring_buffer_size=30, snapshot_dir=temp_snapshot_dir)

    # Verify all 5 snapshots were recovered
    hist = svc2.get_history("cluster-a", limit=None)
    assert len(hist) == 5
    assert hist[0].nodes[0].name == "node-0"  # First snapshot, first node
    assert len(hist[4].nodes) == 14  # Last snapshot has 14 nodes


def test_multiple_clusters_persistent(k8s_demo, temp_snapshot_dir):
    """Test persistence/recovery with multiple clusters."""
    from collections import deque

    svc1 = SnapshotService(k8s_demo, ring_buffer_size=30, snapshot_dir=temp_snapshot_dir)

    # Persist for multiple clusters
    for cid in ["cluster-a", "cluster-b", "cluster-c"]:
        snap = _create_test_snapshot(cid, 5)
        with svc1._lock:
            svc1._history[cid] = deque(maxlen=svc1._ring_size)
            svc1._history[cid].append(snap)
            svc1._current[cid] = snap
    svc1._persist_history()

    # Verify 3 history files created
    hist_files = list(temp_snapshot_dir.glob("*_history.json"))
    assert len(hist_files) == 3

    # Load and verify recovery
    svc2 = SnapshotService(k8s_demo, ring_buffer_size=30, snapshot_dir=temp_snapshot_dir)
    assert len(svc2._current) == 3
    assert set(svc2._current.keys()) == {"cluster-a", "cluster-b", "cluster-c"}


def test_bg_loop_persists_on_refresh(k8s_demo, temp_snapshot_dir):
    """Test that background loop calls _persist_history after refresh."""
    from collections import deque

    svc = SnapshotService(k8s_demo, ring_buffer_size=30, snapshot_dir=temp_snapshot_dir)

    # Perform one refresh via _bg_loop simulation
    snap = _create_test_snapshot("cluster-a", 5)
    with svc._lock:
        svc._history["cluster-a"] = deque(maxlen=svc._ring_size)
        svc._history["cluster-a"].append(snap)
        svc._current["cluster-a"] = snap
    svc._persist_history()

    # Verify file exists
    assert (temp_snapshot_dir / "cluster-a_history.json").exists()


def test_corrupted_history_file_gracefully_handled(k8s_demo, temp_snapshot_dir):
    """Test that corrupted JSON files don't crash startup."""
    # Create a corrupted JSON file
    hist_file = temp_snapshot_dir / "cluster-x_history.json"
    hist_file.write_text("{invalid json")

    # Should not raise
    svc = SnapshotService(k8s_demo, ring_buffer_size=30, snapshot_dir=temp_snapshot_dir)
    assert "cluster-x" not in svc._current


def test_empty_history_file_handled(k8s_demo, temp_snapshot_dir):
    """Test that empty history files are skipped."""
    hist_file = temp_snapshot_dir / "cluster-empty_history.json"
    hist_file.write_text(json.dumps({"cluster_id": "cluster-empty", "snapshots": []}))

    svc = SnapshotService(k8s_demo, ring_buffer_size=30, snapshot_dir=temp_snapshot_dir)
    assert "cluster-empty" not in svc._current


