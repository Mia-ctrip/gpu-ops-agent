"""SkillLoader — register and select skills."""

from __future__ import annotations

import logging
from typing import Any

from .skills.base import Skill

logger = logging.getLogger(__name__)

# Simple keyword → skill mapping for lightweight routing
_KEYWORD_MAP: dict[str, list[str]] = {
    "scheduling_diagnosis": [
        "调度", "schedule", "pending", "调度不上去", "排障", "调度失败",
    ],
    "fragmentation": [
        "碎片", "fragmentation", "腾挪", "binpack", "迁移", "腾出",
    ],
    "incident_impact": [
        "影响", "impact", "宕机", "故障", "notready", "不健康", "维护",
    ],
    "gpu_recommendation": [
        "推荐", "recommend", "资源", "空闲", "可用", "分配", "overview", "汇总",
    ],
}


class SkillLoader:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def select(self, user_question: str, session: Any = None) -> Skill:
        """Select the best matching skill based on keyword matching."""
        question_lower = user_question.lower()

        # Score each skill by keyword hits
        best_name: str | None = None
        best_score = 0
        for skill_name, keywords in _KEYWORD_MAP.items():
            score = sum(1 for kw in keywords if kw in question_lower)
            if score > best_score:
                best_score = score
                best_name = skill_name

        if best_name and best_name in self._skills:
            logger.info("Selected skill: %s (score=%d)", best_name, best_score)
            return self._skills[best_name]

        # Default to first registered skill
        if self._skills:
            default = next(iter(self._skills.values()))
            logger.info("No keyword match, defaulting to: %s", default.name)
            return default

        raise RuntimeError("No skills registered")

    @property
    def skill_names(self) -> list[str]:
        return list(self._skills.keys())
