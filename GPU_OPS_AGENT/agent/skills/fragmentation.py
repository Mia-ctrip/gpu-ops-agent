"""Fragmentation skill — diagnose GPU fragmentation and recommend binpack migrations."""

from __future__ import annotations

from .base import Skill

_INSTRUCTIONS = """
## Fragmentation Diagnosis & Binpack Recommendation

When cluster has enough total free GPU but no single node satisfies the request:

1. **Confirm fragmentation** — use `get_cluster_gpu_summary` for totals, then `list_nodes` with `min_free_gpu=<required>`. If the latter returns empty but total free > required, it's fragmentation.
2. **Identify candidates for腾挪 (腾 = make room)** — use `list_nodes` to find nodes with *some* pods that could be migrated.
3. **Evaluate migration difficulty** — fewer pods to migrate = lower impact. Use `get_node_detail` to see exact pod distribution.
4. **Provide optimal + alternative plans**:
   - **Optimal**: the plan that requires migrating the fewest pods/instances.
   - **Alternatives (2-3)**: other valid plans. Include caveats — e.g. a single-pod service on the "optimal" node might be a critical online service with no DR, making a multi-pod plan with DR actually safer.
5. **Never recommend blindly** — always show the topology of affected nodes so the user can make the final call.
"""


class FragmentationSkill(Skill):
    def __init__(self) -> None:
        super().__init__(
            name="fragmentation",
            instructions=_INSTRUCTIONS,
            allowed_tools=[
                "get_cluster_gpu_summary",
                "list_nodes",
                "get_node_detail",
                "get_pod_gpu_allocation",
                "get_active_alerts",
            ],
        )
