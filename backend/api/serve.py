"""The deployable app: API under /api, the built frontend at /, health at /healthz.

  uvicorn api.serve:build --factory --app-dir backend --host 0.0.0.0 --port 8000

With PUBLIC_DEMO=true it serves one isolated session per visitor, with rate limits
and a daily spend cap; otherwise it is the single-user app (Telegram, scheduler).
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from tripwire.config import REPO_ROOT, Settings

log = logging.getLogger(__name__)
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


def build() -> FastAPI:
    settings = Settings.from_env()
    if settings.public_demo:
        from api.main import create_app
        from api.visitors import VisitorSessions, public_factory
        from tripwire.guard import FileSpendStore, GistSpendStore, SpendGuard

        if settings.spend_store == "gist":
            store = GistSpendStore(settings.spend_gist_token, settings.spend_gist_id)
        elif settings.spend_store == "file":
            store = FileSpendStore(settings.data_dir / "spend.json")
        else:
            raise ValueError(f"SPEND_STORE must be file or gist, got {settings.spend_store!r}")
        guard = SpendGuard(settings.daily_spend_cap_usd, lifetime_cap_usd=settings.lifetime_spend_cap_usd,
                           store=store)
        sessions = VisitorSessions(public_factory(settings, guard), max_sessions=settings.max_visitors)
        api = create_app(sessions, settings=settings, guard=guard)
    else:
        from api.main import build as build_local

        api = build_local()
        guard = None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        if guard is not None:
            guard.flush()  # write any spend still waiting for the next gist sync

    root = FastAPI(title="Tripwire", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @root.get("/healthz")
    def healthz() -> dict[str, object]:
        """Liveness for the host: no model calls, no session state."""
        return {"ok": True, "public_demo": settings.public_demo}

    root.mount("/api", api)
    if FRONTEND_DIST.is_dir():
        root.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    else:
        log.warning("frontend/dist not found; serving the API only (run `npm run build` in frontend/)")
    return root
