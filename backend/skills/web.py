"""fetch_url: HTTP GET, with page text read through the quarantined reader.

In DEMO_MODE only allow-listed hosts are actually requested. Every attempt is
logged as an EgressEvent, so a demo can show exactly what would have left.
"""

import html
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import httpx

from tripwire.events import EgressEvent, EventBus
from tripwire.reader import QuarantinedReader

MAX_BYTES = 2_000_000
SCRIPT_STYLE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
TAG = re.compile(r"<[^>]+>")


def html_to_text(body: str) -> str:
    text = SCRIPT_STYLE.sub(" ", body)
    text = TAG.sub("\n", text)
    text = html.unescape(text)
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def host_allowed(host: str, allowlist: tuple[str, ...]) -> bool:
    host = host.lower()
    return any(host == a or host.endswith("." + a) for a in allowlist)


class Fetcher:
    def __init__(
        self,
        reader: QuarantinedReader,
        bus: EventBus,
        demo_mode: bool = False,
        allowlist: tuple[str, ...] = (),
        http: httpx.Client | None = None,
    ) -> None:
        self.reader = reader
        self.bus = bus
        self.demo_mode = demo_mode
        self.allowlist = allowlist
        self.http = http or httpx.Client(timeout=15, follow_redirects=not demo_mode)

    def fetch(self, url: str, schema: Mapping[str, Any] | None = None) -> dict[str, Any]:
        parsed = urlparse(str(url))
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError(f"not an http(s) URL: {url}")
        if self.demo_mode and not host_allowed(parsed.hostname, self.allowlist):
            self.bus.publish(EgressEvent.build("fetch_url", url, url, False, "demo mode: host not on the allowlist"))
            return {"source": url, "error": "not fetched: demo mode only reaches allow-listed hosts"}

        resp = self.http.get(url, headers={"User-Agent": "Tripwire/0.1"})
        self.bus.publish(EgressEvent.build("fetch_url", url, url, True, f"HTTP {resp.status_code}"))
        body = resp.content[:MAX_BYTES].decode(resp.encoding or "utf-8", errors="replace")
        text = html_to_text(body) if "html" in resp.headers.get("content-type", "html") else body
        result = self.reader.read(text, schema, source=url).to_dict()
        result["status"] = resp.status_code
        return result
