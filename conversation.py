"""Per-session conversation state and an in-memory session store."""

import threading
import time
from dataclasses import dataclass, field

from lead_qualification import LEAD_QUESTIONS


@dataclass
class ConversationState:
    session_id: str
    transcript: list = field(default_factory=list)        # [(role, text)], role in {"user", "assistant"}
    topics: list = field(default_factory=list)            # SOP topics the customer asked about
    unanswered: list = field(default_factory=list)        # questions the SOP could not answer
    escalations: list = field(default_factory=list)       # reasons for every escalation
    lead: dict = field(default_factory=dict)              # field_name -> answer
    lead_index: int = -1                                   # -1 = qualification not started
    last_active: float = field(default_factory=time.time)

    @property
    def qualification_started(self):
        return self.lead_index >= 0

    @property
    def qualification_complete(self):
        return self.lead_index >= len(LEAD_QUESTIONS)

    @property
    def pending_question(self):
        """The lead question we are waiting on, or None."""
        if self.qualification_started and not self.qualification_complete:
            return LEAD_QUESTIONS[self.lead_index]
        return None

    def add(self, role, text):
        self.transcript.append((role, text))
        self.last_active = time.time()


class SessionStore:
    """Thread-safe in-memory store. Swap for Redis/DB in production."""

    def __init__(self, ttl_seconds=60 * 60):
        self._sessions = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def get(self, session_id):
        with self._lock:
            self._prune()
            state = self._sessions.get(session_id)
            if state is None:
                state = ConversationState(session_id=session_id)
                self._sessions[session_id] = state
            return state

    def reset(self, session_id):
        with self._lock:
            self._sessions.pop(session_id, None)

    def _prune(self):
        cutoff = time.time() - self._ttl
        for sid in [s for s, st in self._sessions.items() if st.last_active < cutoff]:
            del self._sessions[sid]
