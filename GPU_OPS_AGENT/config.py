"""Centralised configuration — cluster list, thresholds, poll interval, paths."""

from __future__ import annotations

import os
from pathlib import Path

# ── Cluster aliases ──────────────────────────────────────────────────
# Maps friendly names → canonical cluster IDs
CLUSTER_ALIASES: dict[str, str] = {
    # AI-SHAXY-TCS-PRO1
    "新源智算集群": "AI-SHAXY-TCS-PRO1",
    "智算集群": "AI-SHAXY-TCS-PRO1",
    "松江集群": "AI-SHAXY-TCS-PRO1",
    "超算集群": "AI-SHAXY-TCS-PRO1",
    # SHARB-A
    "日坂集群": "SHARB-A",
    "日坂": "SHARB-A",
    "SHARB": "SHARB-A",
    # SHARE-SGP-ALI-PRO1
    "新加坡集群": "SHARE-SGP-ALI-PRO1",
    "SGP-ALI": "SHARE-SGP-ALI-PRO1",
    # SHARE-SHA-ALI-PRO1
    "阿里云上海集群": "SHARE-SHA-ALI-PRO1",
    "SHA-ALI": "SHARE-SHA-ALI-PRO1",
    # SHAXY-B
    "新源集群": "SHAXY-B",
    "新源B": "SHAXY-B",
    "SHAXY": "SHAXY-B",
}

# Canonical cluster list
CLUSTERS: list[str] = [
    "AI-SHAXY-TCS-PRO1",
    "SHARB-A",
    "SHARE-SGP-ALI-PRO1",
    "SHARE-SHA-ALI-PRO1",
    "SHAXY-B",
]

# ── Snapshot polling ────────────────────────────────────────────────
POLL_INTERVAL_SEC: int = 300  # 5 分钟采集一次
RING_BUFFER_SIZE: int = 50   # 最近约 50 次快照

# ── K8s API endpoint ─────────────────────────────────────────────────
# Resource-topology API (read-only).  Override with GPU_OPS_API_ENDPOINT env var.
K8S_API_ENDPOINT: str = os.environ.get(
    "GPU_OPS_API_ENDPOINT",
    "http://di-playground.sys.ctripcorp.com/api/v1/diplayground/allnodes/clusters/cached",
)
K8S_API_TIMEOUT_SEC: float = 30.0

# ── Alert thresholds ────────────────────────────────────────────────
# Capacity watermark — GPU utilization levels
WATERMARK_CRITICAL: float = 0.9   # alert when usage >= 90% (RED)
WATERMARK_WARNING: float = 0.75   # alert when 75% <= usage < 90% (YELLOW)

# ── Paths ───────────────────────────────────────────────────────────
DATA_DIR: Path = Path(__file__).parent / "data"
SNAPSHOT_DIR: Path = DATA_DIR / "snapshots"

# ── Agent ───────────────────────────────────────────────────────────
MAX_AGENT_ITERATIONS: int = 10

# ── GPU Anomaly Detection Rules ──────────────────────────────────────
# Stage 1: Absolute rules based on operational experience
# Maps cluster_id → gpu_type → set of anomalous Allocatable GPU counts
# Only Allocatable GPU is checked; Available is never used for detection
GPU_ANOMALY_RULES: dict[str, dict[str, set]] = {
    "SHARB-A": {"h20": {5, 7}},              # h20 with 5,7 is anomalous (3 is OK)
    "SHAXY-B": {"h20": {5, 7}},              # h20 with 5,7 is anomalous (3 is OK)
    "SHARE-SHA-ALI-PRO1": {"h20": {3, 5, 7}},   # h20 with 3,5,7 all anomalous
    "SHARE-SGP-ALI-PRO1": {"h20": {3, 5, 7}},   # h20 with 3,5,7 all anomalous
    "AI-SHAXY-TCS-PRO1": {"h20": {3, 5, 7}},    # h20 with 3,5,7 all anomalous
}
