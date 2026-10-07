"""Per-visitor sessions for the public demo.

Each visitor (a random id the browser keeps in localStorage) gets its own
Session: its own chat, memory, notes, approvals, user rules and event stream,
in its own temporary directory. Sessions idle past the TTL, or beyond the cap,
are dropped oldest-first. All visitors share the spend guard.
"""

import re
import shutil
import tempfile
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from tripwire.config import Settings
from tripwire.guard import SpendGuard
from tripwire.session import Session

VISITOR_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
# The visitor's own chat, for the policy. With no bot token nothing reaches Telegram.
PUBLIC_SELF_CHAT = "public-demo-visitor"


class InvalidVisitor(ValueError):
    pass


def public_settings(base: Settings, visitor_dir: Path) -> Settings:
    """Settings for one public visitor: demo files only, no Telegram, own storage."""
    return replace(
        base,
        demo_mode=True,
        telegram_bot_token="",  # nothing is ever delivered from the public demo
        telegram_chat_id=PUBLIC_SELF_CHAT,
        telegram_demo_attacker_chat_id="",
        data_dir=visitor_dir / "data",
        notes_dir=visitor_dir / "notes",
        fetch_allowlist=("127.0.0.1", "localhost"),  # only the demo pages this server hosts
    )


class VisitorSessions:
    def __init__(self, factory: Callable[[str, Path], Session], *, max_sessions: int = 200,
                 idle_ttl_s: float = 2 * 3600, clock: Callable[[], float] = time.monotonic,
                 root: Path | None = None) -> None:
        self.factory = factory
        self.max_sessions = max_sessions
        self.idle_ttl = idle_ttl_s
        self.clock = clock
        self.root = root or Path(tempfile.mkdtemp(prefix="tripwire-visitors-"))
        self._sessions: OrderedDict[str, tuple[Session, float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, visitor_id: str) -> Session:
        if not VISITOR_ID.match(visitor_id or ""):
            raise InvalidVisitor("missing or malformed visitor id")
        now = self.clock()
        with self._lock:
            self._evict(now)
            if visitor_id in self._sessions:
                session, _ = self._sessions.pop(visitor_id)
            else:
                directory = self.root / visitor_id
                directory.mkdir(parents=True, exist_ok=True)
                session = self.factory(visitor_id, directory)
            self._sessions[visitor_id] = (session, now)  # most recently used last
            return session

    def __len__(self) -> int:
        return len(self._sessions)

    def _evict(self, now: float) -> None:
        stale = [vid for vid, (_, seen) in self._sessions.items() if now - seen > self.idle_ttl]
        while len(self._sessions) - len(stale) >= self.max_sessions:
            oldest = next(vid for vid in self._sessions if vid not in stale)
            stale.append(oldest)
        for vid in stale:
            self._sessions.pop(vid, None)
            shutil.rmtree(self.root / vid, ignore_errors=True)


def public_factory(base: Settings, guard: SpendGuard) -> Callable[[str, Path], Session]:
    from tripwire.app import build_session

    def make(visitor_id: str, directory: Path) -> Session:
        settings = public_settings(base, directory)
        return build_session(settings, guard=guard, rules_path=directory / "user_rules.yaml")

    return make
