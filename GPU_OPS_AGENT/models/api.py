"""API-layer models — faithful class expression of the K8s resource-topology API.

The endpoint (`GET .../clusters/cached`) returns a deeply nested dict that uses
*keys as data*, e.g. ``{"Clusters": {"<cluster_name>": {...}}}``.  Instead of
reproducing that "key is the data" habit, every level below is expressed as an
explicit dataclass carrying its own name field, so the structure reads as real
objects:

    ApiResponse
    └── ApiData.clusters: list[ClusterRaw]
        └── ClusterRaw { cluster_name, status, cluster_data }   # 名字字段 + 下一对象
            └── ClusterData { train, infer }                    # ScenarioRaw | None
                └── ScenarioRaw { scenario, total, node_groups }
                    └── GpuTypeGroup { gpu_type, nodes }
                        └── NodeRaw { name, ip, accelerator_type, ... }
                            ├── ResourceValues (allocatable / available)
                            ├── LabelRaw[]
                            ├── TaintRaw[]
                            └── GpuPodRaw[]                     # gpu_distribution

This module is a pure data / deserialisation layer:
  - every class has a ``from_dict`` classmethod (JSON dict → object);
  - no business logic, no dependency on any other project module.
The semantic normalisation (raw → domain) belongs to ``k8s_client``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .domain import ScenarioRole

# ── Parsing helpers ───────────────────────────────────────────────────


def parse_mem_mb(value: Any) -> float:
    """Normalise a memory value reported by the API into MiB.

    Real payloads use strings like ``"514195Mi"``; legacy fixtures may carry a
    bare number.  ``Gi``/``Mi``/``Ki`` (and single-letter forms) are honoured.
    """
    if value is None:
        return 0.0
    s = str(value).strip()
    if not s:
        return 0.0
    suffixes = {
        "Gi": 1024.0, "G": 1024.0,
        "Mi": 1.0, "M": 1.0,
        "Ki": 1.0 / 1024.0, "K": 1.0 / 1024.0,
    }
    unit = s[-2:] if s[-2:] in suffixes else (s[-1:] if s[-1:] in suffixes else "")
    try:
        num = float(s if not unit else s[: -len(unit)])
    except ValueError:
        return 0.0
    return num * suffixes.get(unit, 1.0)


# ── Leaf objects ─────────────────────────────────────────────────────


@dataclass
class ResourceValues:
    """Per-dimension resource numbers for one node (Allocatable / Available).

    ``memory`` keeps the raw API string (e.g. ``"514195Mi"``); use ``memory_mb``
    for the numeric value.  ``from_dict`` tolerates both the real Uppercase keys
    (``CPU``/``GPU``/``Memory``) and legacy lowercase fixtures.
    """

    cpu: float = 0.0
    gpu: int = 0
    memory: str = "0"

    @classmethod
    def from_dict(cls, d: dict) -> "ResourceValues":
        if not isinstance(d, dict):
            d = {}
        return cls(
            cpu=float(d.get("CPU", d.get("cpu", 0) or 0)),
            gpu=int(d.get("GPU", d.get("gpu", 0) or 0)),
            memory=str(d.get("Memory", d.get("mem", "0") or "0")),
        )

    @property
    def memory_mb(self) -> float:
        return parse_mem_mb(self.memory)


@dataclass
class LabelRaw:
    key: str
    value: str

    @classmethod
    def from_dict(cls, d: dict) -> "LabelRaw":
        return cls(key=str(d.get("Key", "")), value=str(d.get("Value", "")))


@dataclass
class TaintRaw:
    key: str
    value: str
    effect: str

    @classmethod
    def from_dict(cls, d: dict) -> "TaintRaw":
        return cls(
            key=str(d.get("Key", "")),
            value=str(d.get("Value", "")),
            effect=str(d.get("Effect", "")),
        )


@dataclass
class GpuPodRaw:
    """One entry of a node's GPUDistribution — a running pod and its GPU count."""

    pod_name: str
    gpu_count: int

    @classmethod
    def from_item(cls, pod_name: str, gpu_count: Any) -> "GpuPodRaw":
        return cls(pod_name=str(pod_name), gpu_count=int(gpu_count))


# ── Node / group / scenario / cluster ────────────────────────────────


@dataclass
class NodeRaw:
    """One host as returned by the API (Name, Ip, AcceleratorType, ...).

    ``gpu_type`` is the *group key* the node is filed under in ``Nodes`` (e.g.
    ``"nvidia-h20"``); ``accelerator_type`` is the node's own field.  In real
    data they match; ``gpu_type`` is kept so a flattened node is self-describing.
    """

    name: str
    ip: str
    gpu_type: str
    accelerator_type: str
    allocatable: ResourceValues
    available: ResourceValues
    labels: list[LabelRaw] = field(default_factory=list)
    taints: list[TaintRaw] = field(default_factory=list)
    status: str = "Ready"
    support_train_infer_swap: bool = False
    gpu_pod_count: int = 0
    gpu_distribution: list[GpuPodRaw] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict, gpu_type: str) -> "NodeRaw":
        dist = d.get("GPUDistribution", {})
        if not isinstance(dist, dict):
            dist = {}

        taints_raw = d.get("Taint", [])
        if not isinstance(taints_raw, list):
            taints_raw = []

        return cls(
            name=str(d.get("Name", "")),
            ip=str(d.get("Ip", "")),
            gpu_type=gpu_type,
            accelerator_type=str(d.get("AcceleratorType", gpu_type)),
            allocatable=ResourceValues.from_dict(d.get("Allocatable", {})),
            available=ResourceValues.from_dict(d.get("Available", {})),
            labels=[LabelRaw.from_dict(x) for x in d.get("Label", []) if isinstance(x, dict)],
            taints=[TaintRaw.from_dict(x) for x in taints_raw if isinstance(x, dict)],
            status=str(d.get("Status", "Ready")),
            support_train_infer_swap=bool(d.get("SupportTrainInferSwap", False)),
            gpu_pod_count=int(d.get("GPUPodCount", 0)),
            gpu_distribution=[GpuPodRaw.from_item(k, v) for k, v in dist.items()],
        )


@dataclass
class GpuTypeGroup:
    """One ``Nodes`` group: a gpu-type key followed by its host list."""

    gpu_type: str
    nodes: list[NodeRaw] = field(default_factory=list)

    @classmethod
    def from_dict(cls, gpu_type: str, raw_nodes: Any) -> "GpuTypeGroup":
        node_list = raw_nodes if isinstance(raw_nodes, list) else []
        return cls(
            gpu_type=gpu_type,
            nodes=[NodeRaw.from_dict(n, gpu_type) for n in node_list if isinstance(n, dict)],
        )


@dataclass
class ScenarioRaw:
    """Train or Infer scenario of a cluster: total host count + nodes by gpu type."""

    scenario: ScenarioRole
    total: int
    node_groups: list[GpuTypeGroup] = field(default_factory=list)

    @classmethod
    def from_dict(cls, scenario_name: str, d: dict) -> "ScenarioRaw":
        if not isinstance(d, dict):
            d = {}
        total = int(d.get("Total", 0) or 0)
        nodes_dict = d.get("Nodes")
        if not isinstance(nodes_dict, dict):
            # Legacy shape: the scenario dict *is* the gpu_type -> nodes map
            # (no Total/Nodes envelope).  Treat it directly as the map.
            nodes_dict = d
        groups = [GpuTypeGroup.from_dict(k, v) for k, v in nodes_dict.items()]
        return cls(
            scenario=ScenarioRole(str(scenario_name)),
            total=total,
            node_groups=groups,
        )

    def all_nodes(self) -> list[NodeRaw]:
        """Flatten every gpu-type group into a single node list."""
        return [node for g in self.node_groups for node in g.nodes]


@dataclass
class ClusterData:
    """The per-cluster payload: the Train and Infer namespaces' data."""

    train: ScenarioRaw | None = None
    infer: ScenarioRaw | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "ClusterData":
        d = d if isinstance(d, dict) else {}
        train = ScenarioRaw.from_dict("Train", d["Train"]) if d.get("Train") is not None else None
        infer = ScenarioRaw.from_dict("Infer", d["Infer"]) if d.get("Infer") is not None else None
        return cls(train=train, infer=infer)


@dataclass
class ClusterRaw:
    """One cluster.  The cluster name is an explicit field, not a dict key.

    Heavier weight on this shape than ``ApiResponse``: in the API the cluster's
    name is the *key* of ``Clusters`` and its value is every other field.  We
    keep it as ``cluster_name`` + ``cluster_data`` so the object is self-describing.
    """

    cluster_name: str
    status: str
    cluster_data: ClusterData

    @classmethod
    def from_dict(cls, cluster_name: str, d: dict) -> "ClusterRaw":
        d = d if isinstance(d, dict) else {}
        return cls(
            cluster_name=cluster_name,
            status=str(d.get("Status", "")),
            cluster_data=ClusterData.from_dict(d.get("Data", {})),
        )


@dataclass
class ApiData:
    """The ``Data`` envelope: a flat list of ClusterRaw (no name-keyed dict)."""

    clusters: list[ClusterRaw] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "ApiData":
        clusters = d.get("Clusters", {}) if isinstance(d, dict) else {}
        if not isinstance(clusters, dict):
            clusters = {}
        return cls(clusters=[ClusterRaw.from_dict(k, v) for k, v in clusters.items()])


@dataclass
class ApiResponse:
    """Top-level envelope returned by the endpoint."""

    code: int
    success: bool
    message: str
    trace_id: str
    data: ApiData | None

    @classmethod
    def from_dict(cls, d: dict) -> "ApiResponse":
        data = d.get("Data") if isinstance(d, dict) else None
        return cls(
            code=int(d.get("Code", 0)) if isinstance(d, dict) else 0,
            success=bool(d.get("Success", False)) if isinstance(d, dict) else False,
            message=str(d.get("Message", "")) if isinstance(d, dict) else "",
            trace_id=str(d.get("TraceID", "")) if isinstance(d, dict) else "",
            data=ApiData.from_dict(data) if isinstance(data, dict) else None,
        )