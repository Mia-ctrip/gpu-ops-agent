"""Thin read-only adapter over the existing K8s API wrapper.

This module is the *only* component in the process that talks to the
Kubernetes API.  It deserialises raw API responses through
``models.api`` (whose classes mirror the endpoint's nested structure without
the "dict key is data" habit) and normalises them into domain models.

Two data sources are supported:
  - a demo JSON file (deterministic, used by tests / local offline runs);
  - the live read-only endpoint (default, see ``config.K8S_API_ENDPOINT``).

It never exposes any write methods.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from pathlib import Path

from config import K8S_API_ENDPOINT, K8S_API_TIMEOUT_SEC
from models.api import ApiResponse, NodeRaw
from models.domain import Node, NodeStatus, PodGpuAllocation, ResourceSpec, ScenarioRole

logger = logging.getLogger(__name__)

# ── AcceleratorType parsing helpers ────────────────────────────────
# Key format: "nvidia-h20", "nvidia-tesla-l20-4-192", etc.
# Returns (gpu_type, gpu_count_on_host, mem_per_gpu_gb)

_GPU_TYPE_MAP: dict[str, str] = {
    "h20": "h20",
    "l20": "l20",
    "a100": "a100",
    "a10": "a10",
    "v100": "v100",
    "t4": "t4",
}


def parse_accelerator_type(accel_type: str) -> tuple[str, int, float]:
    """Parse AcceleratorType string into (gpu_type, gpu_count, mem_per_gpu_gb).

    Examples:
        "nvidia-h20"              → ("h20", 1, 96.0)   # default 96G for h20
        "nvidia-h20-141"          → ("h20-141", 1, 141.0)  # H20 with 141GB variant
        "nvidia-tesla-l20-4-192"  → ("l20", 4, 48.0)   # 192/4=48G each
        "nvidia-tesla-a100-1-80"  → ("a100", 1, 80.0)
    """
    clean = accel_type.replace("nvidia-", "").replace("tesla-", "")
    parts = clean.split("-")
    raw_type = parts[0].lower()

    gpu_count = 1
    mem_per_gpu = None

    # Special handling for H20 memory variants: h20-141, etc.
    if raw_type == "h20" and len(parts) >= 2:
        try:
            mem_val = int(parts[1])
            # If second part is a memory value (100+), treat as memory variant
            if mem_val >= 100:
                return f"h20-{mem_val}", 1, float(mem_val)
        except ValueError:
            pass

    gpu_type = _GPU_TYPE_MAP.get(raw_type, raw_type)
    mem_per_gpu = _default_mem(gpu_type)

    if len(parts) >= 3:
        try:
            gpu_count = int(parts[1])
            total_mem = int(parts[2])
            mem_per_gpu = total_mem / gpu_count
        except (ValueError, ZeroDivisionError):
            pass

    return gpu_type, gpu_count, mem_per_gpu


def _default_mem(gpu_type: str) -> float:
    defaults = {"h20": 96.0, "l20": 48.0, "a100": 80.0, "a10": 24.0, "v100": 32.0, "t4": 16.0}
    return defaults.get(gpu_type, 0.0)


def _resource_spec(values) -> ResourceSpec:
    """Raw ResourceValues → domain ResourceSpec (mem normalised to MiB)."""
    return ResourceSpec(gpu=values.gpu, cpu=values.cpu, mem=values.memory_mb)


class K8sApiError(RuntimeError):
    """Raised when the live endpoint cannot be reached or parsed."""


# ── K8sClient ──────────────────────────────────────────────────────


class K8sClient:
    """Read-only adapter for the GPU resource-topology API.

    ``refresh()`` pulls the latest full payload (all clusters in one call) and
    caches it; ``list_clusters`` / ``fetch_cluster_nodes`` read from that cache,
    lazily loading on first use.  Pass ``demo_data_path`` to run against a local
    file instead of the network (tests, offline debugging).
    """

    def __init__(
        self,
        demo_data_path: str | Path | None = None,
        endpoint: str | None = None,
        timeout: float = K8S_API_TIMEOUT_SEC,
    ):
        self._demo_data_path = Path(demo_data_path) if demo_data_path else None
        self._endpoint = endpoint or K8S_API_ENDPOINT
        self._timeout = timeout
        self._api: ApiResponse | None = None

    # ── public (read-only) ──────────────────────────────────────────

    def refresh(self) -> None:
        """Fetch the latest full payload and replace the cached copy.

        Demo mode re-reads the local file; endpoint mode does one HTTP GET.
        """
        if self._demo_data_path:
            raw_dict = json.loads(self._demo_data_path.read_text())
            self._api = _parse_payload(raw_dict)
            return
        self._api = _parse_payload(self._http_get_json(self._endpoint, self._timeout))

    def list_clusters(self) -> list[str]:
        self._ensure_loaded()
        if self._api and self._api.data:
            return [c.cluster_name for c in self._api.data.clusters]
        return []

    def fetch_cluster_nodes(
        self, cluster_id: str
    ) -> list[tuple[ScenarioRole, list[NodeRaw]]]:
        """Return raw host objects grouped by scenario (Train/Infer).

        Returns list of (scenario, [NodeRaw]) tuples; each NodeRaw is a class
        expression of the API's host object (Name, Ip, Allocatable, ...).
        """
        self._ensure_loaded()
        cluster = self._find_cluster(cluster_id)
        if cluster is None:
            logger.warning("Cluster %s not found in data", cluster_id)
            return []

        result: list[tuple[ScenarioRole, list[NodeRaw]]] = []
        for scenario, scen_raw in (
            (ScenarioRole.TRAIN, cluster.cluster_data.train),
            (ScenarioRole.INFER, cluster.cluster_data.infer),
        ):
            if scen_raw is None:
                continue
            result.append((scenario, scen_raw.all_nodes()))
        return result

    def raw_node_to_domain(self, raw: NodeRaw, cluster_id: str, scenario: ScenarioRole) -> Node:
        """Convert a raw ``NodeRaw`` into a domain Node."""
        gpu_type, _, _ = parse_accelerator_type(raw.gpu_type or raw.accelerator_type)

        pods: list[PodGpuAllocation] = [
            PodGpuAllocation(pod_name=p.pod_name, node_name=raw.name, gpu_count=p.gpu_count)
            for p in raw.gpu_distribution
        ]
        try:
            status = NodeStatus(raw.status)
        except ValueError:
            status = NodeStatus.NOT_READY

        return Node(
            name=raw.name,
            ip=raw.ip,
            cluster_id=cluster_id,
            gpu_type=gpu_type,
            scenario=scenario,
            status=status,
            allocatable=_resource_spec(raw.allocatable),
            available=_resource_spec(raw.available),
            labels={l.key: l.value for l in raw.labels},
            taints=[
                {"key": t.key, "value": t.value, "effect": t.effect} for t in raw.taints
            ],
            pods=pods,
        )

    # ── internal ────────────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        if self._api is None:
            self.refresh()

    def _http_get_json(self, url: str, timeout: float) -> dict:
        """Single read-only GET; returns the decoded JSON body."""
        request = urllib.request.Request(url, headers={"User-Agent": "gpu-ops-agent/0.1", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
        except Exception as exc:  # URLError, HTTPError, socket.timeout, ...
            raise K8sApiError(f"Failed to fetch {url}: {exc}") from exc
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise K8sApiError(f"Endpoint returned non-JSON payload from {url}") from exc
        if not isinstance(payload, dict):
            raise K8sApiError(f"Endpoint returned unexpected payload shape from {url}")
        return payload

    def _find_cluster(self, cluster_id: str):
        """Locate a ClusterRaw by name, or None."""
        if not (self._api and self._api.data):
            return None
        for cluster in self._api.data.clusters:
            if cluster.cluster_name == cluster_id:
                return cluster
        return None


def _parse_payload(raw_dict: dict) -> ApiResponse:
    """JSON payload → ApiResponse.

    The real endpoint wraps clusters in {Code, Success, Message, TraceID, Data};
    legacy fixtures put Clusters at the top level.  Normalise both here.
    """
    if "Data" not in raw_dict and "Clusters" in raw_dict:
        raw_dict = {"Code": 200, "Success": True, "Message": "", "TraceID": "", "Data": raw_dict}
    return ApiResponse.from_dict(raw_dict)