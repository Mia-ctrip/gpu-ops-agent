"""Tests for AlertService — deterministic rules.

Three alert types:
1. NODE_HEALTH: NotReady nodes trigger CRITICAL alerts
2. GPU_REPORTING_ANOMALY: Odd GPU counts (1,3,5,7) or negative available GPU
3. CAPACITY_WATERMARK: Per GPU type — >90% CRITICAL, 75-90% WARNING
"""

from __future__ import annotations

from datetime import datetime, timezone

from models.domain import AlertSeverity, AlertType, Node, NodeStatus, ResourceSpec, ScenarioRole
from models.snapshot import ClusterSnapshot
from services.alert_service import AlertService


def _make_node(
    name: str,
    gpu_type: str = "h20",
    status: str = "Ready",
    alloc_gpu: int = 8,
    avail_gpu: int = 4,
) -> Node:
    return Node(
        name=name,
        ip="10.0.0.1",
        cluster_id="TEST",
        gpu_type=gpu_type,
        scenario=ScenarioRole.TRAIN,
        status=NodeStatus(status),
        allocatable=ResourceSpec(gpu=alloc_gpu, cpu=96, mem=1000000),
        available=ResourceSpec(gpu=avail_gpu, cpu=48, mem=500000),
    )


def _make_snapshot(*nodes: Node) -> ClusterSnapshot:
    return ClusterSnapshot(
        cluster_id="TEST",
        collected_at=datetime.now(timezone.utc),
        nodes=list(nodes),
    )


# ── Node Health ─────────────────────────────────────────────────────


def test_healthy_nodes_no_alert():
    svc = AlertService()
    snap = _make_snapshot(_make_node("n1"), _make_node("n2"))
    alerts = svc.evaluate(snap)
    health_alerts = [a for a in alerts if a.type == AlertType.NODE_HEALTH]
    assert len(health_alerts) == 0


def test_notready_triggers_critical():
    svc = AlertService()
    snap = _make_snapshot(_make_node("n1", status="NotReady"))
    alerts = svc.evaluate(snap)
    health_alerts = [a for a in alerts if a.type == AlertType.NODE_HEALTH]
    assert len(health_alerts) == 1
    assert health_alerts[0].severity == AlertSeverity.CRITICAL
    assert "n1" in health_alerts[0].message


# ── GPU Reporting Anomaly ──────────────────────────────────────────


def test_valid_even_gpu_counts_no_anomaly():
    """GPU counts of 0, 2, 4, 8 are valid."""
    svc = AlertService()
    nodes = [_make_node(f"n{i}", alloc_gpu=g, avail_gpu=g//2) for i, g in enumerate([2, 4, 8])]
    snap = _make_snapshot(*nodes)
    alerts = svc.evaluate(snap)
    anomaly_alerts = [a for a in alerts if a.type == AlertType.GPU_REPORTING_ANOMALY]
    assert len(anomaly_alerts) == 0


def test_odd_gpu_counts_valid_if_in_cluster():
    """Odd GPU counts (1, 3) that appear in cluster data are valid."""
    svc = AlertService()
    # All nodes have odd counts - this is normal for their cluster
    nodes = [
        _make_node("n1", alloc_gpu=1, avail_gpu=0),
        _make_node("n2", alloc_gpu=1, avail_gpu=0),
        _make_node("n3", alloc_gpu=3, avail_gpu=1),
        _make_node("n4", alloc_gpu=3, avail_gpu=1),
    ]
    snap = _make_snapshot(*nodes)
    alerts = svc.evaluate(snap)
    anomaly_alerts = [a for a in alerts if a.type == AlertType.GPU_REPORTING_ANOMALY]
    # No anomalies since 1, 3 are both present in the cluster
    assert len(anomaly_alerts) == 0


def test_multiple_valid_gpu_counts_no_anomaly():
    """All GPU counts that appear in the cluster are valid (even if diverse)."""
    svc = AlertService()
    # Cluster with multiple GPU counts: 1, 2, 4, 8 are all valid
    nodes = [
        _make_node("n1", alloc_gpu=1, avail_gpu=0),
        _make_node("n2", alloc_gpu=2, avail_gpu=1),
        _make_node("n3", alloc_gpu=4, avail_gpu=2),
        _make_node("n4", alloc_gpu=8, avail_gpu=4),
    ]
    snap = _make_snapshot(*nodes)
    alerts = svc.evaluate(snap)
    anomaly_alerts = [a for a in alerts if a.type == AlertType.GPU_REPORTING_ANOMALY]
    # All counts are in the cluster, so NO anomalies
    assert len(anomaly_alerts) == 0


def test_available_exceeds_allocatable_triggers_critical():
    """Available > Allocatable is a critical data corruption issue."""
    svc = AlertService()
    snap = _make_snapshot(_make_node("n1", alloc_gpu=8, avail_gpu=10))
    alerts = svc.evaluate(snap)
    anomaly_alerts = [a for a in alerts if a.type == AlertType.GPU_REPORTING_ANOMALY]
    assert len(anomaly_alerts) == 1
    assert anomaly_alerts[0].severity == AlertSeverity.CRITICAL
    assert "exceeds" in anomaly_alerts[0].message.lower()


# ── Capacity Watermark — Per GPU Type ──────────────────────────────


def test_low_usage_no_watermark_alert():
    """Usage < 75% generates no watermark alert."""
    svc = AlertService()
    snap = _make_snapshot(_make_node("n1", gpu_type="h20", alloc_gpu=8, avail_gpu=6))  # 25% usage
    alerts = svc.evaluate(snap)
    wm_alerts = [a for a in alerts if a.type == AlertType.CAPACITY_WATERMARK]
    assert len(wm_alerts) == 0


def test_medium_usage_triggers_warning():
    """75% <= usage < 90% generates WARNING alert."""
    svc = AlertService()
    # h20: 8 GPUs, available 2 → usage = 6/8 = 75% exactly
    snap = _make_snapshot(_make_node("n1", gpu_type="h20", alloc_gpu=8, avail_gpu=2))
    alerts = svc.evaluate(snap)
    wm_alerts = [a for a in alerts if a.type == AlertType.CAPACITY_WATERMARK]
    assert len(wm_alerts) == 1
    assert wm_alerts[0].severity == AlertSeverity.WARNING
    assert "h20" in wm_alerts[0].message
    assert wm_alerts[0].gpu_type == "h20"


def test_high_usage_triggers_critical():
    """Usage >= 90% generates CRITICAL alert."""
    svc = AlertService()
    # h20: 10 GPUs, available 0 → usage = 100%
    snap = _make_snapshot(_make_node("n1", gpu_type="h20", alloc_gpu=10, avail_gpu=0))
    alerts = svc.evaluate(snap)
    wm_alerts = [a for a in alerts if a.type == AlertType.CAPACITY_WATERMARK]
    assert len(wm_alerts) == 1
    assert wm_alerts[0].severity == AlertSeverity.CRITICAL
    assert "h20" in wm_alerts[0].message
    assert wm_alerts[0].gpu_type == "h20"


def test_watermark_per_gpu_type():
    """Multiple GPU types are evaluated independently."""
    svc = AlertService()
    # h20: 2 nodes × 8 GPU = 16 total, available 4 → 75% usage
    h20_nodes = [
        _make_node("h20-1", gpu_type="h20", alloc_gpu=8, avail_gpu=2),
        _make_node("h20-2", gpu_type="h20", alloc_gpu=8, avail_gpu=2),
    ]
    # l20: 1 node × 8 GPU, available 0 → 100% usage
    l20_nodes = [
        _make_node("l20-1", gpu_type="l20", alloc_gpu=8, avail_gpu=0),
    ]
    snap = _make_snapshot(*h20_nodes, *l20_nodes)
    alerts = svc.evaluate(snap)
    wm_alerts = [a for a in alerts if a.type == AlertType.CAPACITY_WATERMARK]

    # h20 should have WARNING (75%), l20 should have CRITICAL (100%)
    h20_alerts = [a for a in wm_alerts if a.gpu_type == "h20"]
    l20_alerts = [a for a in wm_alerts if a.gpu_type == "l20"]

    assert len(h20_alerts) == 1
    assert h20_alerts[0].severity == AlertSeverity.WARNING
    assert len(l20_alerts) == 1
    assert l20_alerts[0].severity == AlertSeverity.CRITICAL


def test_cpu_nodes_excluded_from_watermark():
    """CPU-only nodes don't trigger watermark alerts."""
    svc = AlertService()
    # CPU node with 0 GPU
    cpu_node = _make_node("cpu-1", gpu_type="cpu", alloc_gpu=0, avail_gpu=0)
    snap = _make_snapshot(cpu_node)
    alerts = svc.evaluate(snap)
    wm_alerts = [a for a in alerts if a.type == AlertType.CAPACITY_WATERMARK]
    assert len(wm_alerts) == 0


def test_notready_nodes_excluded_from_watermark():
    """NotReady nodes are excluded from watermark calculation."""
    svc = AlertService()
    # NotReady h20 node (should be excluded from watermark)
    nr_node = _make_node("h20-notready", gpu_type="h20", status="NotReady", alloc_gpu=8, avail_gpu=0)
    # Ready h20 node with 50% usage (no warning)
    ready_node = _make_node("h20-ready", gpu_type="h20", status="Ready", alloc_gpu=8, avail_gpu=4)
    snap = _make_snapshot(nr_node, ready_node)
    alerts = svc.evaluate(snap)

    # Should have 1 NODE_HEALTH alert for NotReady node
    # Should have 0 CAPACITY_WATERMARK alerts (ready node is only 50%)
    health_alerts = [a for a in alerts if a.type == AlertType.NODE_HEALTH]
    wm_alerts = [a for a in alerts if a.type == AlertType.CAPACITY_WATERMARK]

    assert len(health_alerts) == 1
    assert len(wm_alerts) == 0


def test_watermark_alert_includes_affected_nodes():
    """Watermark alert raw_values include list of affected nodes."""
    svc = AlertService()
    nodes = [
        _make_node("h20-1", gpu_type="h20", alloc_gpu=8, avail_gpu=0),
        _make_node("h20-2", gpu_type="h20", alloc_gpu=8, avail_gpu=0),
    ]
    snap = _make_snapshot(*nodes)
    alerts = svc.evaluate(snap)
    wm_alerts = [a for a in alerts if a.type == AlertType.CAPACITY_WATERMARK]

    assert len(wm_alerts) == 1
    assert "affected_nodes" in wm_alerts[0].raw_values
    affected = wm_alerts[0].raw_values["affected_nodes"]
    assert "h20-1" in affected
    assert "h20-2" in affected


# ── Refresh / Active Alerts ────────────────────────────────────────


def test_refresh_replaces_active_alerts():
    svc = AlertService()
    snap1 = _make_snapshot(_make_node("n1", status="NotReady"))
    svc.refresh(snap1)
    assert len(svc.get_active_alerts()) == 1

    snap2 = _make_snapshot(_make_node("n1", status="Ready"))
    svc.refresh(snap2)
    assert len(svc.get_active_alerts()) == 0


def test_filter_by_cluster():
    svc = AlertService()
    node = _make_node("n1", status="NotReady")
    node.cluster_id = "CLUSTER-A"
    snap = ClusterSnapshot(
        cluster_id="CLUSTER-A",
        collected_at=datetime.now(timezone.utc),
        nodes=[node],
    )
    svc.refresh(snap)
    assert len(svc.get_active_alerts("CLUSTER-A")) > 0
    assert len(svc.get_active_alerts("CLUSTER-B")) == 0
