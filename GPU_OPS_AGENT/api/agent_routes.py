"""Agent chat API route."""

from __future__ import annotations

from dataclasses import asdict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.agent import AgentRuntime

router = APIRouter()

_agent_runtime: AgentRuntime | None = None


def init_runtime(runtime: AgentRuntime) -> None:
    global _agent_runtime
    _agent_runtime = runtime


class ChatRequest(BaseModel):
    session_id: str
    question: str


@router.post("/agent/chat")
def agent_chat(req: ChatRequest) -> dict:
    """Process a user question through the agent runtime."""
    if _agent_runtime is None:
        raise HTTPException(503, "Agent runtime not initialised")
    try:
        decision = _agent_runtime.handle(req.session_id, req.question)
        return asdict(decision)
    except Exception as exc:
        raise HTTPException(500, f"Agent error: {exc}")
