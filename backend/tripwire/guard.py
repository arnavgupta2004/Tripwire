"""Protections for a public demo: spend caps on model calls and rate limits.

Two caps, shared by every visitor: one per UTC day and one for the deployment's
lifetime. Both are persisted, so a restart doesn't reset them, and a state file
that can't be read or written stops model calls rather than forgetting spend.
Costs come from config/pricing.yaml via the model router.
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


class SpendStateError(RuntimeError):
    """The persisted spend can't be read or written; refuse to run without it."""


class SpendGuard:
    def __init__(self, daily_cap_usd: float, state_path: Path | None = None,
                 clock: Callable[[], float] = time.time, *, lifetime_cap_usd: float | None = None) -> None:
        self.cap = daily_cap_usd
        self.lifetime_cap = lifetime_cap_usd
        self.path = state_path
        self.clock = clock
        self._lock = threading.Lock()
        self._day, self._spent, self._lifetime = _today(clock()), 0.0, 0.0
        if state_path is not None:
            if state_path.exists():
                try:
                    state = json.loads(state_path.read_text())
                    self._lifetime = float(state.get("lifetime_usd", state.get("spent_usd", 0.0)))
                    if state.get("day") == self._day:
                        self._spent = float(state.get("spent_usd", 0.0))
                except (ValueError, OSError, TypeError) as exc:
                    raise SpendStateError(f"can't read spend state at {state_path}: {exc}") from exc
            self._save()  # fail at startup, not mid-demo, if the volume isn't writable

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
    def spent_lifetime(self) -> float:
        with self._lock:
            return self._lifetime

    @property
    def lifetime_exhausted(self) -> bool:
        return self.lifetime_cap is not None and self.spent_lifetime >= self.lifetime_cap

    @property
    def exhausted(self) -> bool:
        return self.lifetime_exhausted or self.spent_today >= self.cap

    def check(self) -> None:
        """Raise before a model call once either cap is used up."""
        if self.lifetime_exhausted:
            raise SpendCapReached(f"lifetime spend cap of ${self.lifetime_cap:.2f} reached")
        if self.exhausted:
            raise SpendCapReached(f"daily spend cap of ${self.cap:.2f} reached")

    def add(self, cost_usd: float) -> None:
        with self._lock:
            self._roll()
            self._spent += max(0.0, cost_usd)
            self._lifetime += max(0.0, cost_usd)
            self._save()

    def _save(self) -> None:
        if self.path is None:
            return
        state = {"day": self._day, "spent_usd": round(self._spent, 6), "lifetime_usd": round(self._lifetime, 6)}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state))
            tmp.replace(self.path)  # atomic: a crash mid-write can't corrupt the file
        except OSError as exc:
            raise SpendStateError(f"can't write spend state at {self.path}: {exc}") from exc

    def status(self) -> dict[str, float | str | None]:
        spent, lifetime = self.spent_today, self.spent_lifetime
        out: dict[str, float | str | None] = {
            "day": self._day, "spent_usd": round(spent, 4), "cap_usd": self.cap,
            "remaining_usd": round(max(0.0, self.cap - spent), 4),
            "lifetime_spent_usd": round(lifetime, 4), "lifetime_cap_usd": self.lifetime_cap,
        }
        if self.lifetime_cap is not None:
            out["remaining_usd"] = round(max(0.0, min(self.cap - spent, self.lifetime_cap - lifetime)), 4)
        return out


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
