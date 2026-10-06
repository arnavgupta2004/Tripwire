"""Research skill: Tavily search and extract, always through the quarantined reader."""

from collections.abc import Mapping
from typing import Any

from tripwire.reader import PassthroughReader, QuarantinedReader

MAX_RESULTS = 5
SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                },
            },
        }
    },
}


class Research:
    def __init__(self, tavily: Any, reader: QuarantinedReader | PassthroughReader) -> None:
        self.tavily = tavily  # a TavilyClient (or anything with search/extract)
        self.reader = reader

    def search(self, query: str, max_results: int = MAX_RESULTS) -> list[dict[str, Any]]:
        """Search, then pass titles and snippets through the reader. URLs come from
        Tavily's metadata, not page text."""
        raw = self.tavily.search(query, max_results=min(int(max_results), MAX_RESULTS))
        hits = [r for r in raw.get("results", []) if r.get("url")]
        if not hits:
            return []
        if not getattr(self.reader, "quarantined", True):
            return [{"url": h["url"], "title": h.get("title", ""), "content": h.get("content", "")} for h in hits]
        text = "\n\n".join(f"[{i}] {h.get('title', '')}\n{h.get('content', '')}" for i, h in enumerate(hits))
        read = self.reader.read(text, SEARCH_SCHEMA, source=f"tavily_search:{query}")
        by_index = {r["index"]: r for r in read.data.get("results", [])}
        return [
            {
                "url": h["url"],
                "title": by_index.get(i, {}).get("title", ""),
                "summary": by_index.get(i, {}).get("summary", ""),
                "suspicious_instructions_detected": read.suspicious_instructions_detected,
            }
            for i, h in enumerate(hits)
        ]

    def extract(self, urls: list[str] | str, schema: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        urls = [urls] if isinstance(urls, str) else list(urls)[:MAX_RESULTS]
        raw = self.tavily.extract(urls=urls)
        out = []
        for item in raw.get("results", []):
            read = self.reader.read(item.get("raw_content") or "", schema, source=item.get("url", ""))
            out.append(read.to_dict())
        for failed in raw.get("failed_results", []):
            out.append({"source": failed.get("url", ""), "error": "could not extract this page"})
        return out
