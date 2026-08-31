"""Scheduling Diagnosis skill — diagnose why pods can't be scheduled."""

from __future__ import annotations

from .base import Skill

_INSTRUCTIONS = """
## Scheduling Diagnosis

When a user reports a pod cannot be scheduled (e.g. "pod xxx is Pending"):

1. **Check cluster exists** — use `get_cluster_gpu_summary` to confirm the cluster and get totals.
2. **Check for active alerts** — use `get_active_alerts` to see if there are node health issues or GPU reporting anomalies already detected.
3. **Find candidate nodes** — use `list_nodes` with `min_free_gpu` set to the pod's GPU request. If no candidates exist, the pod can't be scheduled due to GPU shortage.
4. **If no candidates** — check if fragmentation is the cause: are there nodes with *some* free GPU but no single node with enough?
5. **If candidates exist** — check CPU and memory with `get_node_detail` — the bottleneck may not be GPU.
6. **Provide evidence** — cite exact numbers from tool results (node names, GPU counts, statuses).

### Output format
- Diagnosis: clear conclusion (sufficient resources / insufficient / fragmentation / non-GPU bottleneck)
- Evidence: exact field values from tools
- Recommendations: if candidates exist, list them; if fragmented, suggest binpack targets
"""


class SchedulingDiagnosisSkill(Skill):
    def __init__(self) -> None:
        super().__init__(
            name="scheduling_diagnosis",
            instructions=_INSTRUCTIONS,
            allowed_tools=[
                "get_cluster_gpu_summary",
                "list_nodes",
                "get_node_detail",
                "get_pod_gpu_allocation",
                "get_active_alerts",
            ],
        )
