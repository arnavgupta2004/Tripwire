"""Protections for a public demo: spend caps on model calls and rate limits.

Two caps, shared by every visitor: one per UTC day and one for the deployment's
lifetime. Both are persisted (a file on a volume, or a secret GitHub gist on hosts
without a disk), so a restart doesn't reset them; state that can't be read or
written stops model calls rather than forgetting spend.
Costs come from config/pricing.yaml via the model router.
"""

import json
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx

from tripwire.models import SpendCapReached


def _today(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")


class SpendStateError(RuntimeError):
    """The persisted spend can't be read or written; refuse to run without it."""


class SpendStore(Protocol):
    def load(self) -> dict[str, Any] | None: ...
    def save(self, state: dict[str, Any], *, urgent: bool = False) -> None: ...
    @property
    def healthy(self) -> bool: ...
    def flush(self) -> None: ...


class FileSpendStore:
    """A JSON file, written atomically on every change (a mounted volume in deployment)."""

    healthy = True

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text())
        except (ValueError, OSError) as exc:
            raise SpendStateError(f"can't read spend state at {self.path}: {exc}") from exc

    def save(self, state: dict[str, Any], *, urgent: bool = False) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state))
            tmp.replace(self.path)  # atomic: a crash mid-write can't corrupt the file
        except OSError as exc:
            raise SpendStateError(f"can't write spend state at {self.path}: {exc}") from exc

    def flush(self) -> None:
        pass


GIST_API = "https://api.github.com"
GIST_FILE = "tripwire-spend.json"
GIST_DESCRIPTION = "Tripwire public demo: spend caps (do not delete)"


class GistSpendStore:
    """A secret GitHub gist, for hosts without a persistent disk.

    Reads once at startup; writes at most every `min_interval_s` seconds, and at
    once when `urgent` (a cap is close). Writes that keep failing for
    `max_failure_s` mark the store unhealthy, which stops model calls.
    """

    def __init__(self, token: str, gist_id: str = "", *, http: httpx.Client | None = None,
                 min_interval_s: float = 30.0, max_failure_s: float = 120.0,
                 clock: Callable[[], float] = time.monotonic, background: bool = True) -> None:
        if not token:
            raise SpendStateError("SPEND_GIST_TOKEN is not set")
        self.http = http or httpx.Client(timeout=15)
        self.http.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                  "X-GitHub-Api-Version": "2022-11-28"})
        self.min_interval = min_interval_s
        self.max_failure = max_failure_s
        self.clock = clock
        self.background = background
        self._lock = threading.Lock()
        self._pending: dict[str, Any] | None = None
        self._last_write = float("-inf")
        self._first_failure: float | None = None
        self._timer: threading.Timer | None = None
        self.gist_id = gist_id or self._find_or_create()

    def _request(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        # Never include the exception text: it can carry request headers.
        try:
            resp = self.http.request(method, f"{GIST_API}{path}", **kw)
        except httpx.HTTPError as exc:
            raise SpendStateError(f"GitHub gist {method} failed ({type(exc).__name__})") from None
        if resp.status_code >= 300:
            hint = (" (GitHub answers 401/403/404 when the token lacks the account permission"
                    " 'Gists: Read and write')") if resp.status_code in (401, 403, 404) else ""
            raise SpendStateError(f"GitHub gist {method} {path} returned {resp.status_code}{hint}")
        return resp.json()

    def _find_or_create(self) -> str:
        for gist in self._request("GET", "/gists", params={"per_page": 100}):
            if gist.get("description") == GIST_DESCRIPTION and GIST_FILE in gist.get("files", {}):
                return gist["id"]
        created = self._request("POST", "/gists", json={
            "description": GIST_DESCRIPTION, "public": False, "files": {GIST_FILE: {"content": "{}"}}})
        return created["id"]

    def load(self) -> dict[str, Any] | None:
        files = self._request("GET", f"/gists/{self.gist_id}").get("files", {})
        if GIST_FILE not in files:
            raise SpendStateError(f"gist {self.gist_id} has no {GIST_FILE}")
        content = files[GIST_FILE].get("content") or ""
        try:
            state = json.loads(content) if content.strip() else {}
        except ValueError as exc:
            raise SpendStateError(f"can't parse {GIST_FILE}: {exc}") from exc
        return state or None

    def save(self, state: dict[str, Any], *, urgent: bool = False) -> None:
        with self._lock:
            self._pending = dict(state)
            due = self._last_write + self.min_interval
            if urgent or self.clock() >= due:
                self._write_locked()
            else:
                self._schedule_locked(due - self.clock())

    def _write_locked(self) -> None:
        if self._pending is None:
            return
        try:
            self._request("PATCH", f"/gists/{self.gist_id}",
                          json={"files": {GIST_FILE: {"content": json.dumps(self._pending)}}})
        except SpendStateError:
            if self._first_failure is None:
                self._first_failure = self.clock()
            self._schedule_locked(min(self.min_interval, 10.0))
            return
        self._pending, self._first_failure, self._last_write = None, None, self.clock()

    def _schedule_locked(self, delay: float) -> None:
        if not self.background or self._timer is not None:
            return

        def fire() -> None:
            with self._lock:
                self._timer = None
                self._write_locked()

        self._timer = threading.Timer(max(0.0, delay), fire)
        self._timer.daemon = True
        self._timer.start()

    @property
    def healthy(self) -> bool:
        with self._lock:
            return self._first_failure is None or self.clock() - self._first_failure < self.max_failure

    def flush(self) -> None:
        with self._lock:
            self._write_locked()


class SpendGuard:
    def __init__(self, daily_cap_usd: float, state_path: Path | None = None,
                 clock: Callable[[], float] = time.time, *, lifetime_cap_usd: float | None = None,
                 store: SpendStore | None = None, urgent_margin_usd: float = 0.10) -> None:
        self.cap = daily_cap_usd
        self.lifetime_cap = lifetime_cap_usd
        self.store: SpendStore | None = store or (FileSpendStore(state_path) if state_path is not None else None)
        self.clock = clock
        self.urgent_margin = urgent_margin_usd
        self._lock = threading.Lock()
        self._day, self._spent, self._lifetime = _today(clock()), 0.0, 0.0
        if self.store is not None:
            state = self.store.load()
            if state:
                try:
                    self._lifetime = float(state.get("lifetime_usd", state.get("spent_usd", 0.0)))
                    if state.get("day") == self._day:
                        self._spent = float(state.get("spent_usd", 0.0))
                except (ValueError, TypeError, AttributeError) as exc:
                    raise SpendStateError(f"spend state is malformed: {exc}") from exc
            self.store.save(self._state(), urgent=True)  # fail at startup, not mid-demo, if it can't be written

    def _roll(self) -> None:
        today = _today(self.clock())
        if today != self._day:
            self._day, self._spent = today, 0.0

    def _state(self) -> dict[str, Any]:
        return {"day": self._day, "spent_usd": round(self._spent, 6), "lifetime_usd": round(self._lifetime, 6)}

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
    def state_unavailable(self) -> bool:
        """Spend can't be saved right now: stop model calls until it can."""
        return self.store is not None and not self.store.healthy

    @property
    def exhausted(self) -> bool:
        return self.state_unavailable or self.lifetime_exhausted or self.spent_today >= self.cap

    def check(self) -> None:
        """Raise before a model call once either cap is used up (or spend can't be saved)."""
        if self.state_unavailable:
            raise SpendCapReached("spend state can't be saved; model calls paused")
        if self.lifetime_exhausted:
            raise SpendCapReached(f"lifetime spend cap of ${self.lifetime_cap:.2f} reached")
        if self.exhausted:
            raise SpendCapReached(f"daily spend cap of ${self.cap:.2f} reached")

    def add(self, cost_usd: float) -> None:
        with self._lock:
            self._roll()
            self._spent += max(0.0, cost_usd)
            self._lifetime += max(0.0, cost_usd)
            state = self._state()
            left = self.cap - self._spent
            if self.lifetime_cap is not None:
                left = min(left, self.lifetime_cap - self._lifetime)
        if self.store is not None:
            self.store.save(state, urgent=left <= self.urgent_margin)

    def flush(self) -> None:
        if self.store is not None:
            self.store.flush()

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
