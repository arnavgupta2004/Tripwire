"""Serve demo/injection/ on http://127.0.0.1:8765 for local injection demos.

Add `FETCH_ALLOWLIST=127.0.0.1` to .env so demo mode lets fetch_url reach it.

Usage: uv run python scripts/serve_demo.py
"""

import functools
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "demo" / "injection"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765


def main() -> None:
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    print(f"Serving {ROOT} at http://127.0.0.1:{PORT}/  (Ctrl+C to stop)")
    server.serve_forever()


if __name__ == "__main__":
    main()
