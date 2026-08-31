"""Incident Impact skill — assess blast radius of a node failure."""

from __future__ import annotations

from .base import Skill

_INSTRUCTIONS = """
## Incident Impact Analysis

When a node goes NotReady or needs maintenance:

1. **Confirm the incident** — use `get_active_alerts` and `list_nodes` to check the node's status.
2. **Identify affected pods** — use `get_node_detail` to get the full GPUDistribution for the affected node.
3. **Try to identify service owners** — use `get_service_owner` for each affected pod (may be stub/unavailable).
4. **Assess blast radius** — how many pods, how many GPUs, which scenarios (Train vs Infer) are affected.
5. **Provide recommendations**:
   - If pods have DR/multi-replica, the impact is manageable.
   - If pods are single-instance services (especially Infer), flag this as high-risk.
   - Always show the full pod list so the user can verify business impact.
"""


class IncidentImpactSkill(Skill):
    def __init__(self) -> None:
        super().__init__(
            name="incident_impact",
            instructions=_INSTRUCTIONS,
            allowed_tools=[
                "get_cluster_gpu_summary",
                "list_nodes",
                "get_node_detail",
                "get_pod_gpu_allocation",
                "get_active_alerts",
                "get_service_owner",
            ],
        )
