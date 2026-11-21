"""Per-session conversation state and an in-memory session store."""

import threading
import time
from dataclasses import dataclass, field

from business import BusinessConfig, get_business


@dataclass
class ConversationState:
    session_id: str
    business: BusinessConfig = field(default_factory=get_business)
    transcript: list = field(default_factory=list)        # [(role, text)], role in {"user", "assistant"}
    topics: list = field(default_factory=list)            # SOP topics the customer asked about
    unanswered: list = field(default_factory=list)        # questions the SOP could not answer
    escalations: list = field(default_factory=list)       # reasons for every escalation
    lead: dict = field(default_factory=dict)              # field_name -> validated answer
    lead_started: bool = False
    last_active: float = field(default_factory=time.time)

    @property
    def qualification_started(self):
        return self.lead_started

    @property
    def missing_fields(self):
        return [f for f in self.business.lead_fields if f.name not in self.lead]

    @property
    def qualification_complete(self):
        return self.lead_started and not self.missing_fields

    @property
    def pending_field(self):
        """The LeadField we are waiting on, or None."""
        if not self.lead_started:
            return None
        missing = self.missing_fields
        return missing[0] if missing else None

    def start_lead_at(self, field_name, filler="(given earlier)"):
        """Test/eval helper: start qualification with `field_name` as the pending field."""
        self.lead_started = True
        for f in self.business.lead_fields:
            if f.name == field_name:
                return
            self.lead[f.name] = filler
        raise KeyError(field_name)

    def add(self, role, text):
        self.transcript.append((role, text))
        self.last_active = time.time()


class SessionStore:
    """Thread-safe in-memory store keyed by (business, session). Swap for Redis in production."""

    def __init__(self, ttl_seconds=60 * 60):
        self._sessions = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def get(self, session_id, business=None):
        business = business or get_business()
        key = (business.id, session_id)
        with self._lock:
            self._prune()
            state = self._sessions.get(key)
            if state is None:
                state = ConversationState(session_id=session_id, business=business)
                self._sessions[key] = state
            return state

    def reset(self, session_id, business=None):
        business = business or get_business()
        with self._lock:
            self._sessions.pop((business.id, session_id), None)

    def _prune(self):
        cutoff = time.time() - self._ttl
        for key in [k for k, st in self._sessions.items() if st.last_active < cutoff]:
            del self._sessions[key]
