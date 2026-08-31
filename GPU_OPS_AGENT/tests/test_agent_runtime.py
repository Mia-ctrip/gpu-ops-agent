"""Tests for AgentRuntime — skill selection and loop structure."""

from __future__ import annotations

import pytest

from agent.agent import AgentRuntime
from agent.memory import SessionMemoryStore
from agent.skill_loader import SkillLoader
from agent.skills.scheduling_diagnosis import SchedulingDiagnosisSkill
from agent.skills.fragmentation import FragmentationSkill
from agent.skills.incident_impact import IncidentImpactSkill
from agent.skills.gpu_recommendation import GpuRecommendationSkill
from agent.tools.tool_registry import ToolRegistry
from agent.tools.tool_executor import ToolExecutor


@pytest.fixture
def runtime() -> AgentRuntime:
    loader = SkillLoader()
    loader.register(SchedulingDiagnosisSkill())
    loader.register(FragmentationSkill())
    loader.register(IncidentImpactSkill())
    loader.register(GpuRecommendationSkill())

    registry = ToolRegistry()
    executor = ToolExecutor(registry)
    memory_store = SessionMemoryStore()

    return AgentRuntime(
        skill_loader=loader,
        tool_executor=executor,
        memory_store=memory_store,
        llm_client=None,
    )


class TestSkillSelection:
    def test_scheduling_keywords(self, runtime):
        skill = runtime.skill_loader.select("pod调度不上去怎么办")
        assert skill.name == "scheduling_diagnosis"

    def test_fragmentation_keywords(self, runtime):
        skill = runtime.skill_loader.select("集群GPU碎片化严重，需要腾挪")
        assert skill.name == "fragmentation"

    def test_incident_keywords(self, runtime):
        skill = runtime.skill_loader.select("svr-01宕机了，影响范围多大")
        assert skill.name == "incident_impact"

    def test_recommendation_keywords(self, runtime):
        skill = runtime.skill_loader.select("推荐一下空闲GPU资源")
        assert skill.name == "gpu_recommendation"


class TestAgentHandle:
    def test_no_llm_returns_confidence_note(self, runtime):
        decision = runtime.handle("test-session", "集群资源汇总")

        assert decision.session_id == "test-session"
        assert decision.skill_used == "gpu_recommendation"
        assert decision.confidence_note is not None
