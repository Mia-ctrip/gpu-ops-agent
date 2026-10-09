"""FastAPI application entrypoint — GPU Ops Agent.

Wires together:
  - K8sClient (read-only K8s adapter)
  - SnapshotService (single source of truth)
  - AlertService (deterministic rule engine)
  - AgentRuntime (ReAct loop)
  - API routes (dashboard + agent chat)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import CLUSTERS, POLL_INTERVAL_SEC
from k8s_client import K8sClient
from services.snapshot_service import SnapshotService
from services.alert_service import AlertService
from agent.agent import AgentRuntime
from agent.memory import SessionMemoryStore
from agent.skill_loader import SkillLoader
from agent.skills.scheduling_diagnosis import SchedulingDiagnosisSkill
from agent.skills.fragmentation import FragmentationSkill
from agent.skills.incident_impact import IncidentImpactSkill
from agent.skills.gpu_recommendation import GpuRecommendationSkill
from agent.tools.tool_registry import ToolRegistry
from agent.tools.tool_executor import ToolExecutor
from agent.tools.cluster_tools import GetClusterGpuSummary
from agent.tools.node_tools import ListNodes, GetNodeDetail
from agent.tools.incident_tools import GetPodGpuAllocation, GetActiveAlerts, GetServiceOwner
from api import dashboard_router, agent_router, init_services, init_runtime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def build_app(demo_data_path: str | None = None) -> FastAPI:
    """Build and wire all components.  Pass demo_data_path for local testing."""

    # ── Core services ───────────────────────────────────────────────
    k8s = K8sClient(demo_data_path=demo_data_path)
    snapshot_svc = SnapshotService(k8s)
    alert_svc = AlertService()

    # ── Agent tools ─────────────────────────────────────────────────
    registry = ToolRegistry()
    registry.register(GetClusterGpuSummary(snapshot_svc))
    registry.register(ListNodes(snapshot_svc))
    registry.register(GetNodeDetail(snapshot_svc))
    registry.register(GetPodGpuAllocation(snapshot_svc))
    registry.register(GetActiveAlerts(alert_svc))
    registry.register(GetServiceOwner())  # stub

    executor = ToolExecutor(registry)

    # ── Agent skills ────────────────────────────────────────────────
    loader = SkillLoader()
    loader.register(SchedulingDiagnosisSkill())
    loader.register(FragmentationSkill())
    loader.register(IncidentImpactSkill())
    loader.register(GpuRecommendationSkill())

    # ── Agent runtime ───────────────────────────────────────────────
    memory_store = SessionMemoryStore()
    agent_runtime = AgentRuntime(
        skill_loader=loader,
        tool_executor=executor,
        memory_store=memory_store,
        llm_client=None,  # TODO: inject real LLM client
    )

    # ── Wire API routes ─────────────────────────────────────────────
    init_services(snapshot_svc, alert_svc)
    init_runtime(agent_runtime)

    # ── Lifespan: start background refresh ──────────────────────────
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Initial data collection and alert evaluation
        try:
            snapshot_svc.refresh_now()
            # Refresh alerts for all clusters
            for cid in CLUSTERS:
                try:
                    snap = snapshot_svc.get_current(cid)
                    alert_svc.refresh(snap)
                except KeyError:
                    pass
        except Exception:
            logger.exception("Initial snapshot refresh failed")

        # Start background polling with alert evaluation
        original_bg_loop = snapshot_svc._bg_loop

        def enhanced_bg_loop(interval_sec: int) -> None:
            """Wrap the snapshot refresh loop to also evaluate alerts."""
            while not snapshot_svc._bg_stop.is_set():
                try:
                    snapshot_svc.refresh_now()
                    snapshot_svc._persist_history()
                    # Evaluate alerts for each cluster after refresh
                    for cid in CLUSTERS:
                        try:
                            snap = snapshot_svc.get_current(cid)
                            alert_svc.refresh(snap)
                        except KeyError:
                            pass
                except Exception:
                    logger.exception("Background refresh failed")
                snapshot_svc._bg_stop.wait(interval_sec)

        # Monkey-patch the loop to include alert evaluation
        snapshot_svc._bg_loop = enhanced_bg_loop
        snapshot_svc.start_background_refresh(POLL_INTERVAL_SEC)
        logger.info("Application started — polling every %ds with alert evaluation", POLL_INTERVAL_SEC)

        yield

        # Shutdown
        snapshot_svc.stop_background_refresh()
        logger.info("Application stopped")

    app = FastAPI(
        title="GPU Ops Agent",
        description="Read-only GPU cluster observation and diagnosis agent",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS middleware must be added before routes
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(dashboard_router, prefix="/api")
    app.include_router(agent_router, prefix="/api")

    @app.get("/health")
    def health():
        return {"status": "ok", "clusters": CLUSTERS}

    @app.get("/debug/check-gpu-dist")
    def check_gpu_dist():
        """Debug endpoint to check if gpu_distribution is in the code"""
        from api.dashboard_routes import _node_detail
        import inspect
        source = inspect.getsource(_node_detail)
        return {
            "has_gpu_distribution": "gpu_distribution" in source,
            "source_lines": source.split('\n')[1:10]
        }

    return app


# Default app instance for `uvicorn main:app`
# Use real K8S API endpoint (no demo data)
app = build_app(demo_data_path=None)
