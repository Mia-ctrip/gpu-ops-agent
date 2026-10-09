"""SnapshotService — the single source of truth for cluster state.

Responsibilities:
  1. Poll K8s via k8s_client
  2. Normalise into domain models
  3. Hold current snapshot in memory
  4. Maintain a ring buffer of recent snapshots (default 50)
  5. Periodically persist to disk for restart recovery
"""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from config import RING_BUFFER_SIZE, SNAPSHOT_DIR
from k8s_client import K8sClient
from models.domain import ScenarioRole
from models.snapshot import ClusterSnapshot

logger = logging.getLogger(__name__)


class SnapshotService:
    def __init__(
        self,
        k8s_client: K8sClient,
        ring_buffer_size: int = RING_BUFFER_SIZE,
        snapshot_dir: Path = SNAPSHOT_DIR,
    ):
        self._k8s = k8s_client
        self._ring_size = ring_buffer_size
        self._snapshot_dir = snapshot_dir

        self._current: dict[str, ClusterSnapshot] = {}
        self._history: dict[str, deque[ClusterSnapshot]] = {}
        self._lock = threading.Lock()
        self._bg_thread: threading.Thread | None = None
        self._bg_stop = threading.Event()

        # Restore from disk on startup
        self._load_from_disk()

    # ── Public API ──────────────────────────────────────────────────

    def refresh_now(self, cluster_id: str | None = None) -> None:
        """Collect fresh data for one (or all) clusters.

        Pulls the latest full payload from the API once (single HTTP call), then
        builds/updates snapshots.  On a transient API failure the previous
        snapshots are kept and the error is logged.  All snapshots built in one
        round share a single ``collected_at`` timestamp so history/trend data
        from the same poll is directly comparable.
        """
        try:
            self._k8s.refresh()
        except Exception:
            logger.exception("Failed to refresh data from K8s API — keeping last snapshot")
            return

        collected_at = datetime.now(timezone.utc)
        clusters = [cluster_id] if cluster_id else self._k8s.list_clusters()
        for cid in clusters:
            snapshot = self._collect(cid, collected_at)
            if snapshot:
                with self._lock:
                    self._current[cid] = snapshot
                    if cid not in self._history:
                        self._history[cid] = deque(maxlen=self._ring_size)
                    self._history[cid].append(snapshot)

    def get_current(self, cluster_id: str) -> ClusterSnapshot:
        with self._lock:
            snap = self._current.get(cluster_id)
        if snap is None:
            raise KeyError(f"No snapshot for cluster {cluster_id!r}")
        return snap

    def get_history(self, cluster_id: str, limit: int = 50) -> list[ClusterSnapshot]:
        with self._lock:
            hist = list(self._history.get(cluster_id, []))
        if limit is None:
            return hist
        return hist[-limit:] if limit > 0 else []

    def start_background_refresh(self, interval_sec: int) -> None:
        if self._bg_thread and self._bg_thread.is_alive():
            return
        self._bg_stop.clear()
        self._bg_thread = threading.Thread(
            target=self._bg_loop,
            args=(interval_sec,),
            daemon=True,
            name="snapshot-refresh",
        )
        self._bg_thread.start()
        logger.info("Background refresh started (interval=%ds)", interval_sec)

    def stop_background_refresh(self) -> None:
        self._bg_stop.set()
        if self._bg_thread:
            self._bg_thread.join(timeout=5)
        logger.info("Background refresh stopped")

    # ── Internal ────────────────────────────────────────────────────

    def _bg_loop(self, interval_sec: int) -> None:
        while not self._bg_stop.is_set():
            try:
                self.refresh_now()
                self._persist_history()
            except Exception:
                logger.exception("Background refresh failed")
            self._bg_stop.wait(interval_sec)

    def _collect(self, cluster_id: str, collected_at: datetime) -> ClusterSnapshot | None:
        try:
            scenario_groups = self._k8s.fetch_cluster_nodes(cluster_id)
        except Exception:
            logger.exception("Failed to fetch nodes for %s", cluster_id)
            return None

        all_nodes = []
        for scenario, raw_nodes in scenario_groups:
            for raw in raw_nodes:
                try:
                    node = self._k8s.raw_node_to_domain(raw, cluster_id, scenario)
                    all_nodes.append(node)
                except Exception:
                    logger.exception(
                        "Skipping unparseable node %r for cluster %s", getattr(raw, "name", "?"), cluster_id
                    )
                    continue

        return ClusterSnapshot(
            cluster_id=cluster_id,
            collected_at=collected_at,
            nodes=all_nodes,
        )

    def _persist_latest(self) -> None:
        """Write latest snapshot per cluster to disk (ring-buffer recovery)."""
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            for cid, snap in self._current.items():
                path = self._snapshot_dir / f"{cid}.json"
                try:
                    data = {
                        "cluster_id": snap.cluster_id,
                        "collected_at": snap.collected_at.isoformat(),
                        "nodes": [_node_to_dict(n) for n in snap.nodes],
                    }
                    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
                except Exception:
                    logger.exception("Failed to persist snapshot for %s", cid)

    def _persist_history(self) -> None:
        """Write complete ring buffer for all clusters to disk (restart recovery)."""
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            for cid, hist in self._history.items():
                path = self._snapshot_dir / f"{cid}_history.json"
                try:
                    snapshots = [
                        {
                            "cluster_id": s.cluster_id,
                            "collected_at": s.collected_at.isoformat(),
                            "nodes": [_node_to_dict(n) for n in s.nodes],
                        }
                        for s in hist
                    ]
                    data = {"cluster_id": cid, "snapshots": snapshots}
                    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
                except Exception:
                    logger.exception("Failed to persist history for %s", cid)

    def _load_from_disk(self) -> None:
        """Restore ring buffer from disk after restart."""
        if not self._snapshot_dir.exists():
            logger.info("Snapshot directory does not exist, starting with empty cache")
            return

        for hist_file in self._snapshot_dir.glob("*_history.json"):
            try:
                data = json.loads(hist_file.read_text())
                cluster_id = data.get("cluster_id")
                if not cluster_id:
                    logger.warning("History file %s missing cluster_id", hist_file.name)
                    continue

                snapshots = data.get("snapshots", [])
                if not snapshots:
                    logger.info("History file %s is empty", hist_file.name)
                    continue

                # Restore snapshots into ring buffer
                self._history[cluster_id] = deque(maxlen=self._ring_size)
                for snap_data in snapshots:
                    snap = self._dict_to_snapshot(snap_data)
                    if snap:
                        self._history[cluster_id].append(snap)
                        # Last snapshot becomes current
                        self._current[cluster_id] = snap

                logger.info(
                    "Restored %d snapshots for cluster %s from disk",
                    len(self._history[cluster_id]),
                    cluster_id,
                )
            except Exception:
                logger.exception("Failed to load history from %s", hist_file.name)

    def _dict_to_snapshot(self, data: dict) -> ClusterSnapshot | None:
        """Convert persisted JSON dict back to ClusterSnapshot."""
        try:
            from datetime import datetime as dt
            from models.domain import Node, NodeStatus, ScheduleStatus, ResourceSpec, PodGpuAllocation

            cluster_id = data.get("cluster_id")
            collected_at_str = data.get("collected_at")
            nodes_data = data.get("nodes", [])

            if not cluster_id or not collected_at_str:
                return None

            # Parse ISO datetime
            collected_at = dt.fromisoformat(collected_at_str)

            nodes = []
            for node_data in nodes_data:
                try:
                    scenario = ScenarioRole(node_data.get("scenario"))
                    status = NodeStatus(node_data.get("status"))
                    # 处理schedule_status，如果不存在则默认为Schedulable
                    try:
                        schedule_status = ScheduleStatus(node_data.get("schedule_status", "Schedulable"))
                    except ValueError:
                        schedule_status = ScheduleStatus.SCHEDULABLE

                    allocatable_dict = node_data.get("allocatable", {})
                    available_dict = node_data.get("available", {})
                    pods_data = node_data.get("pods", [])

                    allocatable = ResourceSpec(
                        gpu=allocatable_dict.get("gpu", 0),
                        cpu=allocatable_dict.get("cpu", 0),
                        mem=allocatable_dict.get("mem", 0),
                    )
                    available = ResourceSpec(
                        gpu=available_dict.get("gpu", 0),
                        cpu=available_dict.get("cpu", 0),
                        mem=available_dict.get("mem", 0),
                    )

                    pods = [
                        PodGpuAllocation(
                            pod_name=p.get("pod_name"),
                            node_name=p.get("node_name"),
                            gpu_count=p.get("gpu_count", 0),
                        )
                        for p in pods_data
                    ]

                    node = Node(
                        name=node_data.get("name"),
                        ip=node_data.get("ip"),
                        cluster_id=node_data.get("cluster_id"),
                        gpu_type=node_data.get("gpu_type"),
                        scenario=scenario,
                        status=status,
                        schedule_status=schedule_status,
                        allocatable=allocatable,
                        available=available,
                        labels=node_data.get("labels", {}),
                        taints=node_data.get("taints", []),
                        pods=pods,
                    )
                    nodes.append(node)
                except Exception:
                    logger.exception("Failed to restore node from %s", node_data.get("name", "?"))
                    continue

            return ClusterSnapshot(cluster_id=cluster_id, collected_at=collected_at, nodes=nodes)
        except Exception:
            logger.exception("Failed to convert dict to snapshot")
            return None


def _node_to_dict(node) -> dict:
    return {
        "name": node.name,
        "ip": node.ip,
        "cluster_id": node.cluster_id,
        "gpu_type": node.gpu_type,
        "scenario": node.scenario.value,
        "status": node.status.value,
        "schedule_status": node.schedule_status.value,
        "allocatable": {"gpu": node.allocatable.gpu, "cpu": node.allocatable.cpu, "mem": node.allocatable.mem},
        "available": {"gpu": node.available.gpu, "cpu": node.available.cpu, "mem": node.available.mem},
        "labels": node.labels,
        "taints": node.taints,
        "pods": [
            {"pod_name": p.pod_name, "node_name": p.node_name, "gpu_count": p.gpu_count}
            for p in node.pods
        ],
    }
