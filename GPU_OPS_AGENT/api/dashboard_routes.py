"""Dashboard API routes — cluster facts, trends, alerts.

All aggregation here is deterministic over a single ``SnapshotService`` current
or history snapshot — no LLM, no business judgement.  Because tools (step 9)
read the same SnapshotService instance, their numbers agree with these by
construction.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException

from services.alert_service import AlertService
from services.snapshot_service import SnapshotService

router = APIRouter()

# Services are injected via app.state in main.py
_snapshot_service: SnapshotService | None = None
_alert_service: AlertService | None = None


def init_services(snapshot_svc: SnapshotService, alert_svc: AlertService) -> None:
    global _snapshot_service, _alert_service
    _snapshot_service = snapshot_svc
    _alert_service = alert_svc


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/clusters")
def list_clusters() -> dict:
    """Return list of known cluster IDs (canonical order from config)."""
    if _snapshot_service is None:
        raise HTTPException(503, "Services not initialised")
    from config import CLUSTERS
    return {"clusters": CLUSTERS}


@router.get("/clusters/{cluster_id}/facts")
def get_cluster_facts(cluster_id: str, scenario: str | None = None) -> dict:
    """Return the full current-snapshot facts for a cluster.

    Args:
        cluster_id: Cluster identifier
        scenario: Optional scenario filter ('Train' or 'Infer'). If not provided, show all.

    Headline scalars (flat, for stat tiles) + ``by_gpu_type`` / ``by_scenario``
    breakdowns (each as a list of objects with an explicit name field) + a light
    per-node summary.  Every number is summed straight from the snapshot.

    Note: ``node_count`` includes ALL Ready nodes (including CPU-only nodes).
    To get GPU node count by type, use ``by_gpu_type[*].node_count``.
    """
    if _snapshot_service is None:
        raise HTTPException(503, "Services not initialised")
    try:
        snap = _snapshot_service.get_current(cluster_id)
    except KeyError:
        raise HTTPException(404, f"Cluster {cluster_id!r} not found")
    return _compute_cluster_facts(snap, scenario=scenario)


@router.get("/clusters/{cluster_id}/trend")
def get_cluster_trend(cluster_id: str, limit: int = 50, gpu_type: str | None = None, scenario: str | None = None) -> dict:
    """Return historical snapshots for trend analysis grouped by GPU type.

    Args:
        cluster_id: Cluster identifier
        limit: Number of historical snapshots to return (default 50)
        gpu_type: Optional GPU type filter (e.g., 'h20', 'l20'). If provided, only return that type.
        scenario: Optional scenario filter ('Train' or 'Infer'). If not provided, show all.

    Returns:
        {
            "cluster_id": "...",
            "by_gpu_type": {
                "h20": [{"collected_at": "...", "allocatable_gpu": 520, "available_gpu": 42, "used_gpu": 478}, ...],
                "h20-141": [...],
                ...
            }
        }
    """
    if _snapshot_service is None:
        raise HTTPException(503, "Services not initialised")
    history = _snapshot_service.get_history(cluster_id, limit=limit)

    # Build trend data grouped by GPU type
    gpu_type_trends = {}
    for snap in history:
        ready_nodes = [n for n in snap.nodes if n.status.value == "Ready"]

        # Filter by scenario if provided
        if scenario:
            ready_nodes = [n for n in ready_nodes if n.scenario.value == scenario]

        for gpu_t in set(n.gpu_type for n in ready_nodes):
            # Skip CPU type
            if gpu_t == "cpu":
                continue

            # Filter nodes for this GPU type
            nodes_of_type = [n for n in ready_nodes if n.gpu_type == gpu_t]
            if not nodes_of_type:
                continue

            # Aggregate metrics
            allocatable = sum(n.allocatable.gpu for n in nodes_of_type)
            available = sum(n.available.gpu for n in nodes_of_type)
            used = allocatable - available

            if gpu_t not in gpu_type_trends:
                gpu_type_trends[gpu_t] = []

            gpu_type_trends[gpu_t].append({
                "collected_at": snap.collected_at.isoformat(),
                "allocatable_gpu": allocatable,
                "available_gpu": available,
                "used_gpu": used,
            })

    # Filter by gpu_type if provided
    if gpu_type and gpu_type in gpu_type_trends:
        gpu_type_trends = {gpu_type: gpu_type_trends[gpu_type]}
    elif gpu_type and gpu_type not in gpu_type_trends:
        raise HTTPException(404, f"GPU type {gpu_type!r} not found in cluster history")

    # Sort GPU types for consistent ordering
    sorted_trends = {k: gpu_type_trends[k] for k in sorted(gpu_type_trends.keys())}

    return {
        "cluster_id": cluster_id,
        "scenario_filter": scenario,
        "by_gpu_type": sorted_trends,
    }


@router.get("/alerts")
def get_alerts(cluster_id: str | None = None) -> dict:
    """Return active alerts with full details, optionally filtered by cluster.

    Returns alert details including:
    - message: Human-readable alert message
    - severity: INFO | WARNING | CRITICAL
    - affected_nodes: List of node names involved in this alert
    - original_data: Raw values supporting the alert (for debugging)
    """
    if _alert_service is None:
        raise HTTPException(503, "Services not initialised")
    alerts = _alert_service.get_active_alerts(cluster_id)

    return {
        "alert_count": len(alerts),
        "alerts": [_format_alert_detail(a) for a in alerts],
    }


def _format_alert_detail(alert) -> dict:
    """Format an Alert object for API response with full details."""
    return {
        "alert_id": alert.alert_id,
        "cluster_id": alert.cluster_id,
        "type": alert.type.value,
        "severity": alert.severity.value,
        "message": alert.message,
        "detected_at": alert.detected_at.isoformat(),
        # Details for frontend display
        "details": {
            "node_name": alert.node_name,
            "gpu_type": alert.gpu_type,
            "affected_nodes": alert.raw_values.get("affected_nodes", [alert.node_name] if alert.node_name else []),
            "reason": alert.raw_values.get("reason", alert.type.value),
        },
        # Raw data for debugging and verification
        "raw_values": alert.raw_values,
    }


@router.post("/clusters/{cluster_id}/refresh")
def refresh_cluster(cluster_id: str) -> dict:
    """Trigger an immediate refresh for a specific cluster.

    This endpoint manually triggers a K8s API query to fetch the latest data
    for the cluster and adds it to the history. The new snapshot becomes the
    current snapshot and is added to the ring buffer.

    Args:
        cluster_id: Cluster identifier

    Returns:
        {"success": true, "message": "...", "facts": {...}, "history_count": N}
    """
    if _snapshot_service is None:
        raise HTTPException(503, "Services not initialised")

    try:
        # Trigger immediate refresh for this cluster
        _snapshot_service.refresh_now(cluster_id)
        _snapshot_service._persist_history()  # Persist to disk immediately

        # Return updated facts and history count
        snap = _snapshot_service.get_current(cluster_id)
        history = _snapshot_service.get_history(cluster_id, limit=None)

        return {
            "success": True,
            "message": f"Cluster {cluster_id} refreshed successfully",
            "cluster_id": cluster_id,
            "collected_at": snap.collected_at.isoformat(),
            "node_count": len(snap.nodes),
            "history_count": len(history),
        }
    except KeyError:
        raise HTTPException(404, f"Cluster {cluster_id!r} not found")
    except Exception as e:
        raise HTTPException(500, f"Failed to refresh cluster: {str(e)}")


@router.get("/clusters/{cluster_id}/nodes")
def get_cluster_nodes(
    cluster_id: str,
    gpu_type: str | None = None,
    scenario: str | None = None,
    offset: int = 0,
    limit: int = 50
):
    """Return detailed node information with pagination, optionally filtered by GPU type and scenario.

    Args:
        cluster_id: Cluster identifier
        gpu_type: Optional GPU type filter (e.g., 'h20', 'l20'). CPU nodes always excluded.
        scenario: Optional scenario filter ('Train' or 'Infer'). If not provided, show all.
        offset: Starting position for pagination (default 0)
        limit: Number of nodes per page (default 50, max 500)

    Returns paginated nodes sorted by available_gpu descending (most available first).

    Note: This endpoint always excludes CPU nodes. For total node count including CPU,
    see /clusters/{cluster_id}/facts.node_count.
    """
    if _snapshot_service is None:
        raise HTTPException(503, "Services not initialised")

    # Limit to reasonable max
    limit = min(limit, 500)
    if limit < 1:
        limit = 50

    try:
        snap = _snapshot_service.get_current(cluster_id)
    except KeyError:
        raise HTTPException(404, f"Cluster {cluster_id!r} not found")

    # Filter: only Ready nodes, exclude CPU type
    nodes = [n for n in snap.nodes if n.status.value == "Ready" and n.gpu_type != "cpu"]

    # Filter by GPU type if provided
    if gpu_type:
        nodes = [n for n in nodes if n.gpu_type == gpu_type]

    # Filter by scenario if provided
    if scenario:
        nodes = [n for n in nodes if n.scenario.value == scenario]

    if not nodes:
        raise HTTPException(404, f"No Ready nodes found with filters: gpu_type={gpu_type}, scenario={scenario}")

    # Sort by available_gpu descending (most available first)
    nodes = sorted(nodes, key=lambda n: n.available.gpu, reverse=True)

    # Get total count before pagination
    total_count = len(nodes)

    # Apply pagination
    paginated_nodes = nodes[offset:offset + limit]

    return {
        "cluster_id": cluster_id,
        "gpu_type_filter": gpu_type,
        "scenario_filter": scenario,
        "total_node_count": total_count,
        "node_count": len(paginated_nodes),
        "offset": offset,
        "limit": limit,
        "has_next": (offset + limit) < total_count,
        "nodes": [_node_detail(n) for n in paginated_nodes],
    }


def _node_detail(n) -> dict:
    """Return comprehensive node details for display."""
    # Extract accelerator label value if it exists
    accelerator_label = n.labels.get("cloud.ctrip.com/accelerator", "")

    # Convert pod list to display format
    gpu_distribution = [
        {"pod_name": pod.pod_name, "gpu_count": pod.gpu_count}
        for pod in n.pods
    ]

    result = {
        "name": n.name,
        "ip": n.ip,
        "accelerator_type": n.gpu_type,
        "accelerator_label": accelerator_label,
        "gpu": {
            "used": n.allocatable.gpu - n.available.gpu,
            "total": n.allocatable.gpu,
        },
        "cpu": {
            "used": round(n.allocatable.cpu - n.available.cpu, 2),
            "total": round(n.allocatable.cpu, 2),
        },
        "memory_mb": {
            "used": round(n.allocatable.mem - n.available.mem, 2),
            "total": round(n.allocatable.mem, 2),
        },
        "status": n.status.value,
        "scenario": n.scenario.value,
        "schedule_status": n.schedule_status.value,
        "gpu_distribution": gpu_distribution,
    }

    return result


# ── Facts aggregation (pure, testable) ──────────────────────────────


def _compute_cluster_facts(snap, scenario: str | None = None) -> dict:
    """Deterministic aggregation of one ClusterSnapshot into facts JSON.

    GPU-focused: only counts Ready nodes for summary statistics.

    Args:
        snap: ClusterSnapshot
        scenario: Optional scenario filter ('Train' or 'Infer'). If not provided, show all.
    """
    nodes = snap.nodes
    ready_nodes = [n for n in nodes if n.status.value == "Ready"]

    # Filter by scenario if provided
    if scenario:
        ready_nodes = [n for n in ready_nodes if n.scenario.value == scenario]

    total_gpu = sum(n.allocatable.gpu for n in ready_nodes)
    available_gpu = sum(n.available.gpu for n in ready_nodes)
    not_ready = [n for n in nodes if n.status.value != "Ready"]

    # If scenario filter is applied, only count NotReady nodes from same scenario
    if scenario:
        not_ready = [n for n in not_ready if n.scenario.value == scenario]

    return {
        "cluster_id": snap.cluster_id,
        "collected_at": snap.collected_at.isoformat(),
        "scenario_filter": scenario,
        # headline GPU resources (flat, for dashboard stat tiles)
        "node_count": len(ready_nodes),
        "gpu_total": total_gpu,
        "gpu_used": total_gpu - available_gpu,
        "gpu_available": available_gpu,
        "utilization_percent": round((total_gpu - available_gpu) / total_gpu * 100, 1) if total_gpu > 0 else 0,
        # health
        "ready_nodes": len(ready_nodes),
        "not_ready_nodes": len(not_ready),
        "not_ready_nodes_list": [n.name for n in not_ready],
        # breakdowns — lists of objects with an explicit name field (Ready nodes only)
        "by_gpu_type": _group_facts(ready_nodes, lambda n: n.gpu_type, "gpu_type"),
        "by_scenario": _group_facts(ready_nodes, lambda n: n.scenario.value, "scenario"),
        # light per-node summary (no pod-level detail here)
        "nodes": [_node_facts(n) for n in ready_nodes],
    }


def _group_facts(nodes, key_fn, label_name: str) -> list[dict]:
    """Group nodes by ``key_fn`` and aggregate GPU resources per bucket.

    Only counts Ready nodes. Returns ``[{label_name, node_count, allocatable_gpu,
    used_gpu, available_gpu, utilization_percent}, ...]`` sorted by allocatable_gpu
    (descending).
    """
    buckets: dict[str, dict] = {}
    for n in nodes:
        # Skip NotReady nodes for GPU summary
        if n.status.value != "Ready":
            continue
        label = key_fn(n)
        b = buckets.setdefault(
            label,
            {
                "node_count": 0,
                "allocatable_gpu": 0,
                "available_gpu": 0,
            },
        )
        b["node_count"] += 1
        b["allocatable_gpu"] += n.allocatable.gpu
        b["available_gpu"] += n.available.gpu

    result = []
    for label, b in buckets.items():
        # Skip "cpu" gpu_type (nodes without actual GPUs)
        if label_name == "gpu_type" and label == "cpu":
            continue

        total_gpu = b["allocatable_gpu"]
        used_gpu = total_gpu - b["available_gpu"]
        utilization = (used_gpu / total_gpu * 100) if total_gpu > 0 else 0
        result.append({
            label_name: label,
            "node_count": b["node_count"],
            "allocatable_gpu": total_gpu,
            "used_gpu": used_gpu,
            "available_gpu": b["available_gpu"],
            "utilization_percent": round(utilization, 1),
        })

    # Sort by allocatable_gpu descending
    return sorted(result, key=lambda x: x["allocatable_gpu"], reverse=True)


def _node_facts(n) -> dict:
    return {
        "name": n.name,
        "ip": n.ip,
        "gpu_type": n.gpu_type,
        "scenario": n.scenario.value,
        "status": n.status.value,
        "allocatable_gpu": n.allocatable.gpu,
        "available_gpu": n.available.gpu,
        "gpu_pod_count": len(n.pods),
    }