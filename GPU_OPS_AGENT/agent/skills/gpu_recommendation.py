"""GPU Recommendation skill — advise on GPU resource allocation."""

from __future__ import annotations

from .base import Skill

_INSTRUCTIONS = """
## GPU Recommendation

When the user asks about GPU resource availability or allocation advice:

1. **Get cluster overview** — use `get_cluster_gpu_summary` to understand total/used/free resources.
2. **Drill down by type** — if the user cares about a specific GPU type, filter by `gpu_type`.
3. **Identify idle waste** — nodes with Available > 0 but GPUPodCount == 0 may be underutilised.
4. **Scenario breakdown** — show Train vs Infer split so the user can rebalance if needed.
5. **Provide actionable summary**:
   - Total free GPUs by type and scenario.
   - Which nodes have the most free capacity (good scheduling targets).
   - Any anomalies (NotReady nodes, reporting issues) that reduce effective capacity.
"""


class GpuRecommendationSkill(Skill):
    def __init__(self) -> None:
        super().__init__(
            name="gpu_recommendation",
            instructions=_INSTRUCTIONS,
            allowed_tools=[
                "get_cluster_gpu_summary",
                "list_nodes",
                "get_node_detail",
                "get_active_alerts",
            ],
        )
