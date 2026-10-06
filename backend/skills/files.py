"""Files skill: read and BM25-search text files in one configured folder."""

import re
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json", ".yaml", ".yml"}
MAX_READ_CHARS = 20_000
SNIPPET_CHARS = 240
TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


class FileStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._docs: list[tuple[str, str]] = []
        self._bm25: BM25Okapi | None = None
        self.reindex()

    def reindex(self) -> None:
        self._docs = []
        if self.root.is_dir():
            for path in sorted(self.root.rglob("*")):
                if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
                    rel = path.relative_to(self.root).as_posix()
                    self._docs.append((rel, path.read_text(errors="replace")))
        corpus = [tokenize(f"{name} {text}") for name, text in self._docs]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def resolve(self, path: str) -> Path:
        """Map a user/planner path to a file inside the root, or raise."""
        raw = Path(str(path).strip()).expanduser()
        candidate = (raw if raw.is_absolute() else self.root / raw).resolve()
        if candidate.is_relative_to(self.root) and candidate.is_file():
            return candidate
        # Planners often guess the folder part: match by file name, inside the root only.
        matches = [self.root / name for name, _ in self._docs if Path(name).name == raw.name]
        if len(matches) == 1:
            return matches[0]
        raise FileNotFoundError(f"no such file in the files folder: {path}")

    def read(self, path: str) -> dict[str, Any]:
        file = self.resolve(path)
        text = file.read_text(errors="replace")
        truncated = len(text) > MAX_READ_CHARS
        return {
            "path": file.relative_to(self.root).as_posix(),
            "content": text[:MAX_READ_CHARS],
            "truncated": truncated,
        }

    def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        if self._bm25 is None:
            return []
        terms = tokenize(query)
        if not terms:
            return []
        scores = self._bm25.get_scores(terms)
        ranked = sorted(zip(scores, self._docs), key=lambda x: -x[0])
        results = []
        for score, (name, text) in ranked[:k]:
            if score <= 0:
                continue
            results.append({"path": name, "score": round(float(score), 3), "snippet": _snippet(text, terms)})
        return results

    @property
    def paths(self) -> list[str]:
        return [name for name, _ in self._docs]


def _snippet(text: str, terms: list[str]) -> str:
    lower = text.lower()
    hits = [i for t in terms if (i := lower.find(t)) >= 0]
    start = max(0, min(hits) - 60) if hits else 0
    snippet = " ".join(text[start : start + SNIPPET_CHARS].split())
    return snippet + ("…" if start + SNIPPET_CHARS < len(text) else "")
