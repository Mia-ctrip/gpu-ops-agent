"""SessionMemory — per-session context for multi-turn conversations.

Stores conversation context (not real-time facts — those come from SnapshotService).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionMemory:
    session_id: str
    current_cluster: str | None = None
    current_pod: str | None = None
    current_gpu_type: str | None = None
    current_issue: str | None = None
    last_diagnosis: str | None = None
    candidate_plans: list[dict] = field(default_factory=list)
    conversation_history: list[dict] = field(default_factory=list)


class SessionMemoryStore:
    """Thread-safe in-memory store for session memories."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionMemory] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> SessionMemory:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionMemory(session_id=session_id)
            return self._sessions[session_id]

    def update(self, session_id: str, **kwargs: Any) -> None:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionMemory(session_id=session_id)
            mem = self._sessions[session_id]
            for key, value in kwargs.items():
                if hasattr(mem, key):
                    setattr(mem, key, value)
