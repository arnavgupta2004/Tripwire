"""Memory skill: long-term facts in SQLite, each stored with its label."""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from skills.files import tokenize
from tripwire.labels import Confidentiality, Integrity, Label, Labeled

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    fact TEXT NOT NULL,
    confidentiality TEXT NOT NULL,
    integrity TEXT NOT NULL,
    sources TEXT NOT NULL,
    created_at REAL NOT NULL
)
"""


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute(SCHEMA)
        self.db.commit()

    def remember(self, fact: str, label: Label) -> Labeled[str]:
        item = Labeled(fact.strip(), label)
        self.db.execute(
            "INSERT INTO facts VALUES (?, ?, ?, ?, ?, ?)",
            (
                item.id,
                item.value,
                str(label.confidentiality),
                str(label.integrity),
                json.dumps(sorted(label.sources)),
                time.time(),
            ),
        )
        self.db.commit()
        return item

    def recall(self, query: str, limit: int = 5) -> list[Labeled[str]]:
        terms = set(tokenize(query))
        facts = self.all()
        if not terms:
            return facts[:limit]
        scored = [(len(terms & set(tokenize(f.value))), f) for f in facts]
        return [f for score, f in sorted(scored, key=lambda x: -x[0]) if score > 0][:limit]

    def all(self) -> list[Labeled[str]]:
        rows = self.db.execute(
            "SELECT id, fact, confidentiality, integrity, sources FROM facts ORDER BY created_at DESC"
        ).fetchall()
        return [
            Labeled(
                fact,
                Label(Confidentiality[conf.upper()], Integrity[integ.upper()], frozenset(json.loads(sources))),
                id=fid,
            )
            for fid, fact, conf, integ, sources in rows
        ]

    def forget(self, fact_id: str) -> bool:
        cur = self.db.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        self.db.commit()
        return cur.rowcount > 0


def fact_view(item: Labeled[str]) -> dict[str, Any]:
    """How a recalled fact appears to the planner: value plus provenance."""
    return {"id": item.id, "fact": item.value, "label": item.label.to_dict()}
