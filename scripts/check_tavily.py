"""Check Tavily access with one search and one extract call.

Usage: uv run python scripts/check_tavily.py
"""

import sys

from tavily import TavilyClient

from _common import load_env, require

QUERY = "NVIDIA Nemotron 3 open models"
FALLBACK_URL = "https://en.wikipedia.org/wiki/Prompt_injection"


def main() -> int:
    load_env()
    client = TavilyClient(api_key=require("TAVILY_API_KEY"))

    try:
        search = client.search(QUERY, max_results=5)
    except Exception as exc:  # tavily raises several unrelated exception types
        print(f"error: search failed: {exc}")
        return 1
    results = search.get("results", [])
    print(f"search {QUERY!r}: {len(results)} results")
    for r in results:
        print(f"  - {r.get('title')}  <{r.get('url')}>")

    url = results[0]["url"] if results else FALLBACK_URL
    try:
        extract = client.extract(urls=[url])
    except Exception as exc:
        print(f"error: extract failed: {exc}")
        return 1
    extracted = extract.get("results", [])
    failed = extract.get("failed_results", [])
    chars = sum(len(r.get("raw_content") or "") for r in extracted)
    print(f"\nextract {url}: {len(extracted)} ok, {len(failed)} failed, {chars:,} chars")

    if not results or not extracted:
        print("FAIL: Tavily returned no results.")
        return 1
    print("OK: Tavily search and extract work.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
