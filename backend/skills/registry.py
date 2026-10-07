"""Wire the real skills into Tripwire's tool registry."""

from dataclasses import dataclass
from typing import Any

from skills.files import FileStore
from skills.memory import MemoryStore, fact_view
from skills.messaging import TelegramSender
from skills.notes import NotesStore
from skills.research import Research
from skills.web import Fetcher
from tripwire.config import Settings
from tripwire.events import EventBus
from tripwire.models import ModelRouter
from tripwire.reader import PassthroughReader, QuarantinedReader
from tripwire.tools import ToolRegistry, build_default_registry


@dataclass
class Skills:
    registry: ToolRegistry
    files: FileStore
    memory: MemoryStore
    notes: NotesStore
    telegram: TelegramSender
    research: Research | None
    fetcher: Fetcher
    reader: QuarantinedReader

    def set_quarantine(self, on: bool) -> None:
        """Route untrusted web content through the quarantined reader (protected) or hand
        it to the planner raw (naive agent)."""
        reader = self.reader if on else PassthroughReader()
        if self.research is not None:
            self.research.reader = reader
        self.fetcher.reader = reader


class NotConfigured(RuntimeError):
    pass


def _require(value: Any, what: str) -> Any:
    if value is None:
        raise NotConfigured(f"{what} is not configured")
    return value


def build_skills(
    settings: Settings,
    router: ModelRouter,
    bus: EventBus,
    *,
    tavily: Any | None = None,
    http: Any | None = None,
    reader: QuarantinedReader | None = None,
) -> Skills:
    reader = reader or QuarantinedReader(router, bus=bus)
    if tavily is None and settings.tavily_api_key:
        from tavily import TavilyClient

        tavily = TavilyClient(api_key=settings.tavily_api_key)
    research = Research(tavily, reader) if tavily is not None else None
    files = FileStore(settings.files_dir)
    memory = MemoryStore(settings.data_dir / "memory.sqlite")
    notes = NotesStore(settings.notes_dir)
    telegram = TelegramSender(
        settings.telegram_bot_token,
        settings.telegram_chat_id,
        bus,
        demo_mode=settings.demo_mode,
        demo_attacker_chat_id=settings.telegram_demo_attacker_chat_id,
        http=http,
    )
    fetcher = Fetcher(reader, bus, demo_mode=settings.demo_mode, allowlist=settings.fetch_allowlist, http=http)

    handlers = {
        "tavily_search": lambda a, _: _require(research, "Tavily (TAVILY_API_KEY)").search(
            a["query"], a.get("max_results", 5)
        ),
        "tavily_extract": lambda a, _: _require(research, "Tavily (TAVILY_API_KEY)").extract(
            a.get("urls") or a.get("url") or [], a.get("schema")
        ),
        "read_file": lambda a, _: files.read(a["path"]),
        "search_files": lambda a, _: files.search(a["query"], a.get("k", 5)),
        "remember": lambda a, label: fact_view(memory.remember(a["fact"], label)),
        "recall": lambda a, _: memory.recall(a.get("query", "")),
        "send_telegram": lambda a, _: telegram.send(a["text"], a.get("chat_id")),
        "write_note": lambda a, _: notes.write(a.get("title", "Note"), a.get("body", "")),
        "fetch_url": lambda a, _: fetcher.fetch(a["url"], a.get("schema")),
    }
    registry = build_default_registry(settings.telegram_chat_id, handlers=handlers)
    return Skills(registry, files, memory, notes, telegram, research, fetcher, reader)
