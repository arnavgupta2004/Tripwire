"""Protections for a public demo: a daily spend cap on model calls and rate limits.

The spend cap is shared by every visitor and persisted, so a restart doesn't
reset it. Costs come from config/pricing.yaml via the model router.
"""

import json
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from tripwire.models import SpendCapReached


def _today(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")


class SpendGuard:
    def __init__(self, daily_cap_usd: float, state_path: Path | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.cap = daily_cap_usd
        self.path = state_path
        self.clock = clock
        self._lock = threading.Lock()
        self._day, self._spent = _today(clock()), 0.0
        if state_path is not None and state_path.exists():
            try:
                state = json.loads(state_path.read_text())
                if state.get("day") == self._day:
                    self._spent = float(state.get("spent_usd", 0.0))
            except (ValueError, OSError):
                pass

    def _roll(self) -> None:
        today = _today(self.clock())
        if today != self._day:
            self._day, self._spent = today, 0.0

    @property
    def spent_today(self) -> float:
        with self._lock:
            self._roll()
            return self._spent

    @property
    def exhausted(self) -> bool:
        return self.spent_today >= self.cap

    def check(self) -> None:
        """Raise before a model call once today's cap is used up."""
        if self.exhausted:
            raise SpendCapReached(f"daily spend cap of ${self.cap:.2f} reached")

    def add(self, cost_usd: float) -> None:
        with self._lock:
            self._roll()
            self._spent += max(0.0, cost_usd)
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps({"day": self._day, "spent_usd": round(self._spent, 6)}))

    def status(self) -> dict[str, float | str]:
        spent = self.spent_today
        return {"day": self._day, "spent_usd": round(spent, 4), "cap_usd": self.cap,
                "remaining_usd": round(max(0.0, self.cap - spent), 4)}


class RateLimiter:
    """At most `limit` events per `window_s` seconds per key (sliding window)."""

    def __init__(self, limit: int, window_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window = window_s
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self.clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def retry_after(self, key: str) -> float:
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return 0.0
            return max(0.0, self.window - (self.clock() - hits[0]))
