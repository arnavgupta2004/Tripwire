"""`tripwire chat`: an interactive session that shows every gateway decision."""

import argparse
import json
import os
import sys
from typing import Any

from tripwire.config import Settings

DIM, RED, GREEN, AMBER, BOLD, RESET = "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[1m", "\033[0m"
VERDICT_COLOR = {"ALLOW": GREEN, "BLOCK": RED, "NEEDS_APPROVAL": AMBER}


def _c(color: str, text: str) -> str:
    return f"{color}{text}{RESET}" if sys.stdout.isatty() and not os.environ.get("NO_COLOR") else text


def _args(args: dict[str, Any], limit: int = 110) -> str:
    text = json.dumps(args, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def print_event(event: Any) -> None:
    if event.kind == "model_call":
        cost = "unpriced" if event.cost_usd is None else f"${event.cost_usd:.5f}"
        status = "" if event.ok else f" FAILED ({event.error})"
        think = " +reasoning" if event.reasoning else ""
        print(_c(DIM, f"      · {event.tier:<5} {event.purpose:<16} {event.latency_ms:6.0f} ms  "
                      f"{event.tokens_in}→{event.tokens_out} tok  {cost}{think}{status}"))
    elif event.kind == "decision":
        models = ", ".join(event.models) or "none"
        verdict = _c(VERDICT_COLOR.get(event.verdict, ""), event.verdict)
        flow = f"{event.labels['data']['confidentiality']}/{event.labels['data']['integrity']}"
        summary = event.args_summary if len(event.args_summary) <= 110 else event.args_summary[:109] + "…"
        print(f"  ▸ {_c(BOLD, event.tool)} {summary}")
        print(f"    {verdict}  {event.rule_id}  ·  data {flow}  ·  models: {models}")
        if event.verdict != "ALLOW" or event.rule_id.startswith("R1") or event.rule_id.startswith("R5"):
            print(_c(DIM, f"    reason: {event.reason}"))
        if event.explanation:
            print(f"    {_c(AMBER, 'judge:')} {event.explanation}")
    elif event.kind == "egress":
        sent = _c(GREEN, "delivered") if event.delivered else _c(AMBER, "NOT delivered")
        canaries = f"  {_c(RED, 'CANARIES: ' + ', '.join(event.canaries))}" if event.canaries else ""
        print(f"    ⇢ {event.tool} → {event.target}: {sent} ({event.note}){canaries}")
    elif event.kind == "block_explanation":
        print(f"    {_c(AMBER, 'why:')} {event.explanation}  {_c(DIM, '(evidence: ' + event.evidence + ')')}")


MODE_ANSWER = {"yes": "allow", "no": "deny"}


def _ask_approval(info: Any, mode: str) -> str:
    print(_c(AMBER, f"\n  Tripwire paused: {info.tool} {_args(info.args)}"))
    print(f"  {info.explanation or info.reason}")
    if info.evidence:
        print(_c(DIM, f"  source: {info.evidence}"))
    if mode != "ask":
        print(f"  (auto-{mode} by --approve {mode})")
        return MODE_ANSWER[mode]
    try:
        choice = input("  [a]llow once / [d]eny / [x] always deny this pattern? ").strip().lower()
    except EOFError:
        return "deny"
    return {"a": "allow", "allow": "allow", "x": "always_deny"}.get(choice, "deny")


def run_turn(session: Any, message: str, approve: str) -> None:
    scheduled = session.maybe_schedule_brief(message)
    if scheduled is not None:
        print(f"\n{_c(BOLD, 'tripwire>')} {scheduled}\n")
        return
    outcome = session.chat(message, source="cli", approver=lambda info: _ask_approval(info, approve))
    print(f"\n{_c(BOLD, 'tripwire>')} {outcome.reply}\n")


def chat(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="tripwire chat")
    parser.add_argument("--shield", choices=["on", "off"], default="on")
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--approve", choices=["ask", "yes", "no"], default="ask",
                        help="how to answer approval prompts (yes/no for scripted runs)")
    parser.add_argument("-m", "--message", action="append", default=[],
                        help="send this message and exit (repeatable, one turn each)")
    parser.add_argument("--fresh-memory", action="store_true", help="use an empty memory database")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    if not settings.api_key:
        print("NEBIUS_API_KEY is not set. Copy .env.example to .env and fill it in.", file=sys.stderr)
        return 2
    if args.shield == "off" and not settings.demo_mode:
        print("--shield off needs DEMO_MODE=true (canary files only).", file=sys.stderr)
        return 2
    if args.fresh_memory:
        import tempfile
        from dataclasses import replace
        from pathlib import Path

        settings = replace(settings, data_dir=Path(tempfile.mkdtemp(prefix="tripwire-")))

    from tripwire.app import build_session

    session = build_session(settings, shield=args.shield == "on", max_steps=args.max_steps)
    session.bus.subscribe(print_event)
    shield = _c(GREEN, "ON") if args.shield == "on" else _c(RED, "OFF (demo, ungated)")
    print(f"Tripwire chat · shield {shield} · judge tier {settings.effective_judge_tier} · "
          f"files {settings.files_dir} · demo mode {'on' if settings.demo_mode else 'off'}")

    if args.message:
        for message in args.message:
            print(f"\n{_c(BOLD, 'you>')} {message}")
            run_turn(session, message, args.approve)
        print(_c(DIM, session.router.usage_summary()["headline"]))
        return 0

    print("Commands: /usage  /memory  /brief_now  /new  /quit\n")
    while True:
        badge = session.planner.context_label.badge
        prompt = f"{_c(AMBER, '[' + badge + '] ')}{_c(BOLD, 'you> ')}" if badge else _c(BOLD, "you> ")
        try:
            message = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not message:
            continue
        if message in {"/quit", "/exit"}:
            break
        if message == "/usage":
            print(json.dumps(session.router.usage_summary(), indent=2))
            continue
        if message == "/memory":
            for fact in session.skills.memory.all():
                lab = fact.label
                mark = "" if lab.is_trusted else "  ⚠ untrusted (info only)"
                print(f"  - {fact.value}  [{lab.confidentiality}/{lab.integrity}; {', '.join(sorted(lab.sources))}]{mark}")
            for task in session.skills.memory.tasks():
                print(f"  · daily brief at {task.schedule}: {task.topic}")
            continue
        if message == "/brief_now":
            run_turn_outcome = session.run_brief()
            print(f"\n{_c(BOLD, 'tripwire>')} {run_turn_outcome.reply}\n")
            continue
        if message == "/new":
            session.new_thread()
            print("  (new conversation)")
            continue
        run_turn(session, message, args.approve)
    print(_c(DIM, session.router.usage_summary()["headline"]))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in {"-h", "--help"}:
        print("usage: tripwire chat [--shield on|off] [--approve ask|yes|no] [-m MESSAGE] [--max-steps N]")
        return 0 if argv else 1
    if argv[0] == "chat":
        return chat(argv[1:])
    print(f"unknown command: {argv[0]}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
