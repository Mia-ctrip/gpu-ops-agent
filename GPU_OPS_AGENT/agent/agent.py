"""AgentRuntime — ReAct loop orchestration.

This module contains NO domain knowledge.  It knows how to:
  1. Select a skill via SkillLoader
  2. Loop: think → call tool → observe → repeat
  3. Produce a structured AgentDecision

Domain logic lives in Skills (prompt instructions) and Tools (deterministic computation).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from config import MAX_AGENT_ITERATIONS
from models.agent import AgentDecision, Evidence, ToolCallRecord
from .memory import SessionMemory, SessionMemoryStore
from .skill_loader import SkillLoader
from .tools.tool_executor import ToolExecutor

logger = logging.getLogger(__name__)


class AgentRuntime:
    def __init__(
        self,
        skill_loader: SkillLoader,
        tool_executor: ToolExecutor,
        memory_store: SessionMemoryStore,
        llm_client: Any = None,  # LLM client — to be injected
        max_iterations: int = MAX_AGENT_ITERATIONS,
    ) -> None:
        self.skill_loader = skill_loader
        self.tool_executor = tool_executor
        self.memory_store = memory_store
        self.llm_client = llm_client
        self.max_iterations = max_iterations

    def handle(self, session_id: str, user_question: str) -> AgentDecision:
        """Process a user question and return a structured decision."""
        memory = self.memory_store.get(session_id)

        # 1. Select skill
        skill = self.skill_loader.select(user_question, memory)
        logger.info("Session %s → skill=%s", session_id, skill.name)

        # 2. Build system prompt from skill
        system_prompt = skill.build_system_prompt()

        # 3. Update session memory with context
        self.memory_store.update(session_id, current_issue=user_question)

        # 4. ReAct loop (placeholder — needs real LLM client)
        tool_calls: list[ToolCallRecord] = []

        if self.llm_client is None:
            return AgentDecision(
                session_id=session_id,
                skill_used=skill.name,
                diagnosis="Agent runtime not fully configured — LLM client not provided.",
                evidence=[Evidence(
                    source="agent_runtime",
                    cluster_id=memory.current_cluster or "unknown",
                    node_name=None,
                    field_path="llm_client",
                    value="None",
                )],
                tool_calls=tool_calls,
                confidence_note="LLM client not configured; cannot perform reasoning.",
            )

        # ── ReAct loop skeleton ─────────────────────────────────────
        # messages = [
        #     {"role": "system", "content": system_prompt},
        #     {"role": "user", "content": user_question},
        # ]
        #
        # for iteration in range(self.max_iterations):
        #     response = self.llm_client.chat(messages, tools=skill.allowed_tools)
        #
        #     if response.is_final:
        #         return self._parse_decision(session_id, skill.name, response, tool_calls)
        #
        #     if response.tool_call:
        #         record = self.tool_executor.execute(
        #             response.tool_call.name, response.tool_call.args
        #         )
        #         tool_calls.append(record)
        #         messages.append({"role": "tool", "content": json.dumps(record.result)})
        #
        # return AgentDecision(...)  # max iterations reached

        return AgentDecision(
            session_id=session_id,
            skill_used=skill.name,
            diagnosis="ReAct loop not yet connected to LLM.",
            tool_calls=tool_calls,
            confidence_note="Implementation pending LLM client integration.",
        )
