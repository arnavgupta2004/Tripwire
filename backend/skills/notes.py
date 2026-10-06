"""Notes skill: write markdown notes into a local folder."""

import re
import time
from pathlib import Path

MAX_NOTE_CHARS = 20_000


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or "note"


class NotesStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, title: str, body: str) -> dict[str, str]:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{slugify(title)}.md"
        if path.exists():
            path = self.root / f"{slugify(title)}-{time.strftime('%Y%m%d-%H%M%S')}.md"
        path.write_text(f"# {title.strip() or 'Note'}\n\n{body.strip()[:MAX_NOTE_CHARS]}\n")
        return {"path": str(path), "title": title}
