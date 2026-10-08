"""FastAPI surface over the assistant. CLI, API and Telegram share one core.

Locally it serves one Session. As a public demo it serves one Session per
visitor (VisitorSessions), with rate limits and a shared daily spend cap.
POST /chat streams the turn's events (SSE); GET /events is a live WebSocket feed
of the visitor's EventBus; approvals, memory, usage, shield and threads round out the API.
"""

import asyncio
import json
import queue
import threading
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from skills.memory import fact_view
from tripwire.session import Session

if TYPE_CHECKING:
    from api.visitors import VisitorSessions


class ChatIn(BaseModel):
    message: str


class ApprovalIn(BaseModel):
    answer: str  # allow | deny | always_deny


class ShieldIn(BaseModel):
    on: bool


class SecurityIn(BaseModel):
    level: str


class RunNowIn(BaseModel):
    topic: str | None = None


def _sse(kind: str, payload: Any) -> str:
    return f"event: {kind}\ndata: {json.dumps(payload, default=str)}\n\n"


def _step_dict(step: Any) -> dict[str, Any]:
    d = step.decision
    return {"tool": step.tool, "args": step.args, "verdict": str(d.verdict), "rule_id": d.rule_id,
            "reason": d.reason, "explanation": d.explanation, "models": list(d.models), "shield": step.shield}


CAP_MESSAGE = ("Tripwire's public demo has used today's model budget, so live chat is paused until "
               "tomorrow (UTC). The Evidence page still works, and you can run Tripwire locally with your "
               "own Token Factory key (see the README).")
STATE_MESSAGE = ("Tripwire's public demo can't record its model spend right now, so live chat is paused "
                 "until it can. Please try again in a few minutes; the Evidence page still works.")
LIFETIME_CAP_MESSAGE = ("Tripwire's public demo has used its total model budget, so live chat is now closed. "
                        "The Evidence page still works, and you can run Tripwire locally with your own "
                        "Token Factory key (see the README).")


def _rate_message(wait_s: float) -> str:
    return (f"You're sending messages faster than the public demo allows. Please wait about "
            f"{max(1, round(wait_s))} seconds and try again.")


def create_app(provider: "Session | VisitorSessions", *, settings: Any = None, guard: Any = None) -> FastAPI:
    """`provider` is one Session (local, single user) or VisitorSessions (public demo)."""
    from fastapi.responses import JSONResponse

    from api.visitors import InvalidVisitor, VisitorSessions
    from tripwire.guard import RateLimiter
    from tripwire.models import SpendCapReached

    public = isinstance(provider, VisitorSessions)
    settings = settings or provider.settings
    app = FastAPI(title="Tripwire")
    app.state.provider = provider
    per_visitor = RateLimiter(settings.chat_rate_per_visitor, 600) if public else None
    everyone = RateLimiter(settings.chat_rate_global, 600) if public else None

    # The frontend dev server (Vite) runs on a different port, so allow local origins.
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if settings.demo_mode:
        # Serve the demo pages from the API so the seeded demo needs no extra server.
        from fastapi.staticfiles import StaticFiles

        from tripwire.config import REPO_ROOT

        app.mount("/demo-pages", StaticFiles(directory=REPO_ROOT / "demo" / "injection"), name="demo-pages")

    def visitor_of(conn: Any) -> str:
        return conn.headers.get("x-tripwire-visitor") or conn.query_params.get("visitor") or ""

    def sess(conn: Any) -> Session:
        return provider.get(visitor_of(conn)) if public else provider

    @app.exception_handler(InvalidVisitor)
    def invalid_visitor(_request: Request, exc: InvalidVisitor) -> JSONResponse:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    def cap_message() -> str:
        if guard is not None and guard.state_unavailable:
            return STATE_MESSAGE
        return LIFETIME_CAP_MESSAGE if guard is not None and guard.lifetime_exhausted else CAP_MESSAGE

    def limited(conn: Any) -> str | None:
        """A friendly message if this request must not reach the models, else None."""
        if guard is not None and guard.exhausted:
            return cap_message()
        if public:
            key = visitor_of(conn)
            if not per_visitor.allow(key):
                return _rate_message(per_visitor.retry_after(key))
            if not everyone.allow("all"):
                return _rate_message(everyone.retry_after("all"))
        return None

    @app.get("/health")
    def health(request: Request) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": True, "demo_mode": settings.demo_mode, "public_demo": public}
        if not public or visitor_of(request):
            session = sess(request)
            out.update(shield=session.shield, mode=session.mode, security=session.security)
        if guard is not None:
            out["budget"] = guard.status()
        return out

    @app.post("/chat")
    def chat(body: ChatIn, request: Request) -> StreamingResponse:
        session = sess(request)
        scheduled = None if public else session.maybe_schedule_brief(body.message)
        blocked = limited(request)

        def stream():
            if blocked is not None:
                yield _sse("done", {"reply": blocked, "steps": [], "limited": True})
                return
            if scheduled is not None:
                yield _sse("done", {"reply": scheduled, "steps": []})
                return
            q: queue.Queue = queue.Queue()
            unsub = session.bus.subscribe(lambda e: q.put(e.to_dict()))
            box: dict[str, Any] = {}

            def run():
                try:
                    box["outcome"] = session.chat(body.message, source="api")
                except SpendCapReached:
                    box["limited"] = cap_message()
                except Exception as exc:  # pragma: no cover - surfaced to the client
                    box["error"] = str(exc)
                finally:
                    q.put(None)

            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            while True:
                event = q.get()
                if event is None:
                    break
                yield _sse(event.get("kind", "event"), event)
            unsub()
            worker.join()
            if "limited" in box:
                yield _sse("done", {"reply": box["limited"], "steps": [], "limited": True})
            elif "error" in box:
                yield _sse("error", {"error": box["error"]})
            else:
                outcome = box["outcome"]
                yield _sse("done", {"reply": outcome.reply, "steps": [_step_dict(s) for s in outcome.steps]})

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.websocket("/events")
    async def events(ws: WebSocket) -> None:
        try:
            session = sess(ws)
        except InvalidVisitor:
            await ws.close(code=1008)
            return
        await ws.accept()
        loop = asyncio.get_event_loop()
        q: asyncio.Queue = asyncio.Queue()
        unsub = session.bus.subscribe(lambda e: loop.call_soon_threadsafe(q.put_nowait, e.to_dict()))
        try:
            for event in list(session.bus.recent):  # replay recent so late joiners see context
                await ws.send_json(event.to_dict())
            while True:
                await ws.send_json(await q.get())
        except WebSocketDisconnect:
            pass
        finally:
            unsub()

    @app.get("/session/usage")
    def usage(request: Request) -> dict[str, Any]:
        return sess(request).router.usage_summary()

    @app.get("/session/context")
    def context(request: Request) -> dict[str, Any]:
        session = sess(request)
        label = session.planner.context_label
        return {
            "private": label.is_private,
            "untrusted": not label.is_trusted,
            "sources": sorted(label.sources),
            "badge": label.badge,
            "thread_started": session.thread_started,
        }

    @app.get("/approvals")
    def approvals(request: Request) -> list[dict[str, Any]]:
        return [a.to_dict() for a in sess(request).broker.pending()]

    @app.get("/approvals/{approval_id}")
    def approval(approval_id: str, request: Request) -> dict[str, Any]:
        info = sess(request).broker.get(approval_id)
        return info.to_dict() if info else {"error": "not found"}

    @app.post("/approvals/{approval_id}")
    def answer(approval_id: str, body: ApprovalIn, request: Request) -> dict[str, Any]:
        if body.answer not in ("allow", "deny", "always_deny"):
            return {"ok": False, "error": "answer must be allow, deny or always_deny"}
        won = sess(request).broker.resolve(approval_id, body.answer)  # first answer wins
        return {"ok": True, "accepted": won}

    @app.get("/memory")
    def memory(request: Request) -> dict[str, Any]:
        mem = sess(request).skills.memory
        return {
            "facts": [fact_view(f) for f in mem.all()],
            "tasks": [{"id": t.id, "kind": t.kind, "topic": t.topic, "schedule": t.schedule} for t in mem.tasks()],
        }

    @app.delete("/memory/{item_id}")
    def forget(item_id: str, request: Request) -> dict[str, Any]:
        mem = sess(request).skills.memory
        removed = mem.remove_task(item_id) if item_id.startswith("t_") else mem.forget(item_id)
        return {"ok": removed}

    @app.post("/shield")
    def shield(body: ShieldIn, request: Request) -> dict[str, Any]:
        session = sess(request)
        try:
            session.set_shield(body.on)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "shield": session.shield, "mode": session.mode}

    @app.post("/security")
    def security(body: SecurityIn, request: Request) -> dict[str, Any]:
        """Protected mode's level: standard (gateway) or high (gateway + quarantined reader)."""
        session = sess(request)
        try:
            session.set_security(body.level)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "security": session.security}

    @app.post("/thread/new")
    def thread_new(request: Request) -> dict[str, Any]:
        sess(request).new_thread()
        return {"ok": True}

    @app.post("/routines/run_now")
    def run_now(body: RunNowIn, request: Request) -> dict[str, Any]:
        session = sess(request)
        blocked = limited(request)
        if blocked is not None:
            return {"ok": False, "reply": blocked, "limited": True}
        try:
            outcome = session.run_brief(body.topic)
        except SpendCapReached:
            return {"ok": False, "reply": cap_message(), "limited": True}
        return {"ok": True, "reply": outcome.reply}

    @app.post("/demo/load")
    def demo_load(request: Request) -> dict[str, Any]:
        session = sess(request)
        if not session.settings.demo_mode:
            return {"ok": False, "error": "demo load is only available in DEMO_MODE"}
        # The demo page is served by this API and fetched server-side, so build its URL from
        # the address this server is bound to (not the browser's Host, which may be a proxy),
        # plus any mount prefix (the public build serves the API under /api).
        host, port = request.scope.get("server") or ("127.0.0.1", 8000)
        if host in ("0.0.0.0", "::", ""):
            host = "127.0.0.1"
        root = request.scope.get("root_path", "")
        return {"ok": True, **session.seed_demo(f"http://{host}:{port}{root}/")}

    return app


def build() -> FastAPI:
    """Entrypoint for `uvicorn api.main:build --factory`."""
    import logging
    import os

    from tripwire.app import build_session
    from tripwire.config import Settings

    session = build_session(Settings.from_env())
    session.start_scheduler()
    settings = session.settings
    # Telegram as an interface (chat + approval cards). TELEGRAM_BOT=off disables it.
    if settings.telegram_bot_token and settings.telegram_chat_id and os.environ.get("TELEGRAM_BOT", "on") != "off":
        try:
            from api.telegram import start_in_background

            start_in_background(session)
        except Exception:
            logging.getLogger(__name__).exception("could not start the Telegram bot")
    return create_app(session)
