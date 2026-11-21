"""Small in-process rate limiter for the public demo.

Protects the Groq quota on a public URL: a sliding-window limit per client IP,
plus an optional global daily cap. In-memory, so it assumes one app process
(the Docker image runs a single gunicorn worker with threads). For several
processes, use Redis.
"""

import threading
import time
from collections import defaultdict, deque


def parse_rate(spec):
    """'20/60' -> (20, 60.0): 20 requests per 60 seconds. '0' or '' disables."""
    if not spec or spec.strip() == "0":
        return None
    count, _, window = spec.partition("/")
    return int(count), float(window or 60)


class RateLimiter:
    def __init__(self, per_client=None, daily=0):
        self.per_client = per_client          # (count, window_seconds) or None
        self.daily = daily                    # max requests per UTC day across everyone, 0 = off
        self._hits = defaultdict(deque)
        self._day = None
        self._day_count = 0
        self._lock = threading.Lock()

    def check(self, key):
        """Return None if allowed, else a reason string. Counts the request when allowed."""
        now = time.time()
        with self._lock:
            today = time.strftime("%Y-%m-%d", time.gmtime(now))
            if today != self._day:
                self._day, self._day_count = today, 0
            if self.daily and self._day_count >= self.daily:
                return "The demo has reached its daily message limit. Please try again tomorrow."

            if self.per_client:
                count, window = self.per_client
                hits = self._hits[key]
                while hits and hits[0] <= now - window:
                    hits.popleft()
                if len(hits) >= count:
                    return "You're sending messages too quickly. Please wait a moment and try again."
                hits.append(now)
                if len(self._hits) > 10_000:  # keep memory bounded
                    for k in [k for k, v in self._hits.items() if not v]:
                        del self._hits[k]

            self._day_count += 1
            return None
