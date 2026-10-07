"""FastAPI surface over a single Session. CLI, API and Telegram share one core.

POST /chat streams the turn's events (SSE); GET /events is a live WebSocket feed
of the EventBus; approvals, memory, usage, shield and threads round out the API.
"""

import asyncio
import json
import queue
import threading
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from skills.memory import fact_view
from tripwire.session import Session


class ChatIn(BaseModel):
    message: str


class ApprovalIn(BaseModel):
    answer: str  # allow | deny | always_deny


class ShieldIn(BaseModel):
    on: bool


class RunNowIn(BaseModel):
    topic: str | None = None


def _sse(kind: str, payload: Any) -> str:
    return f"event: {kind}\ndata: {json.dumps(payload, default=str)}\n\n"


def _step_dict(step: Any) -> dict[str, Any]:
    d = step.decision
    return {"tool": step.tool, "args": step.args, "verdict": str(d.verdict), "rule_id": d.rule_id,
            "reason": d.reason, "explanation": d.explanation, "models": list(d.models), "shield": step.shield}


def create_app(session: Session) -> FastAPI:
    app = FastAPI(title="Tripwire")
    app.state.session = session

    # The frontend dev server (Vite) runs on a different port, so allow local origins.
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if session.settings.demo_mode:
        # Serve the demo pages from the API so the seeded demo needs no extra server.
        from fastapi.staticfiles import StaticFiles

        from tripwire.config import REPO_ROOT

        app.mount("/demo-pages", StaticFiles(directory=REPO_ROOT / "demo" / "injection"), name="demo-pages")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "shield": session.shield, "mode": session.mode, "demo_mode": session.settings.demo_mode}

    @app.post("/chat")
    def chat(body: ChatIn) -> StreamingResponse:
        scheduled = session.maybe_schedule_brief(body.message)

        def stream():
            if scheduled is not None:
                yield _sse("done", {"reply": scheduled, "steps": []})
                return
            q: queue.Queue = queue.Queue()
            unsub = session.bus.subscribe(lambda e: q.put(e.to_dict()))
            box: dict[str, Any] = {}

            def run():
                try:
                    box["outcome"] = session.chat(body.message, source="api")
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
            if "error" in box:
                yield _sse("error", {"error": box["error"]})
            else:
                outcome = box["outcome"]
                yield _sse("done", {"reply": outcome.reply, "steps": [_step_dict(s) for s in outcome.steps]})

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.websocket("/events")
    async def events(ws: WebSocket) -> None:
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
    def usage() -> dict[str, Any]:
        return session.router.usage_summary()

    @app.get("/session/context")
    def context() -> dict[str, Any]:
        label = session.planner.context_label
        return {
            "private": label.is_private,
            "untrusted": not label.is_trusted,
            "sources": sorted(label.sources),
            "badge": label.badge,
        }

    @app.get("/approvals")
    def approvals() -> list[dict[str, Any]]:
        return [a.to_dict() for a in session.broker.pending()]

    @app.get("/approvals/{approval_id}")
    def approval(approval_id: str) -> dict[str, Any]:
        info = session.broker.get(approval_id)
        return info.to_dict() if info else {"error": "not found"}

    @app.post("/approvals/{approval_id}")
    def answer(approval_id: str, body: ApprovalIn) -> dict[str, Any]:
        if body.answer not in ("allow", "deny", "always_deny"):
            return {"ok": False, "error": "answer must be allow, deny or always_deny"}
        won = session.broker.resolve(approval_id, body.answer)  # first answer wins
        return {"ok": True, "accepted": won}

    @app.get("/memory")
    def memory() -> dict[str, Any]:
        return {
            "facts": [fact_view(f) for f in session.skills.memory.all()],
            "tasks": [{"id": t.id, "kind": t.kind, "topic": t.topic, "schedule": t.schedule}
                      for t in session.skills.memory.tasks()],
        }

    @app.delete("/memory/{item_id}")
    def forget(item_id: str) -> dict[str, Any]:
        mem = session.skills.memory
        removed = mem.remove_task(item_id) if item_id.startswith("t_") else mem.forget(item_id)
        return {"ok": removed}

    @app.post("/shield")
    def shield(body: ShieldIn) -> dict[str, Any]:
        try:
            session.set_shield(body.on)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "shield": session.shield, "mode": session.mode}

    @app.post("/thread/new")
    def thread_new() -> dict[str, Any]:
        session.new_thread()
        return {"ok": True}

    @app.post("/routines/run_now")
    def run_now(body: RunNowIn) -> dict[str, Any]:
        outcome = session.run_brief(body.topic)
        return {"ok": True, "reply": outcome.reply}

    @app.post("/demo/load")
    def demo_load(request: Request) -> dict[str, Any]:
        if not session.settings.demo_mode:
            return {"ok": False, "error": "demo load is only available in DEMO_MODE"}
        # The demo page is served by this API; the agent fetches it server-side, so use the
        # address this server is bound to (not the browser's Host, which may be the UI proxy).
        host, port = request.scope.get("server") or ("127.0.0.1", 8000)
        return {"ok": True, **session.seed_demo(f"http://{host}:{port}/")}

    return app


def build() -> FastAPI:
    """Entrypoint for `uvicorn api.main:build --factory`."""
    from tripwire.app import build_session
    from tripwire.config import Settings

    session = build_session(Settings.from_env())
    session.start_scheduler()
    return create_app(session)
