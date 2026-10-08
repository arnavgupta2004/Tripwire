"""Run AgentDojo tasks under one condition and append results to JSONL.

  uv run --group eval python evals/agentdojo/run.py --suite slack --condition none --mode utility
  uv run --group eval python evals/agentdojo/run.py --suite slack --condition tripwire_full --mode attack
  ... --trust strict        Tripwire strict trust domain (only the user is self)
  ... --limit 5 --tag dry   a small dry run, written to a separate file
  ... --policy strict       Tripwire's strict policy profile (v2 behaviour)

Tripwire runs record the policy profile and version. Runs under policy v3 or later
go to their own files (suffix __policy-v3), so they never mix with v2 results.

Utility mode runs each user task once with no injection. Attack mode runs every
(user task, injection task) pair with AgentDojo's published `important_instructions`
attack. In AgentDojo's terms `security=True` means the attacker's goal was met.
"""

import argparse
import json
import logging
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adapter import CONDITIONS, ROOT, build_pipeline, check_mapping, load_mapping  # noqa: E402

from agentdojo.attacks.attack_registry import load_attack  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402

from tripwire.config import Settings  # noqa: E402
from tripwire.models import Pricing  # noqa: E402
from tripwire.policy.engine import PolicyEngine, policy_file  # noqa: E402

BENCHMARK_VERSION = "v1.2.2"
ATTACK = "important_instructions"
RAW = Path(__file__).with_name("results") / "raw"


def policy_suffix(condition: str, profile: str) -> str:
    """'' for v2 (the original files), else e.g. '__policy-v3' or '__policy-strict-v2'."""
    if not condition.startswith("tripwire"):
        return ""
    version = PolicyEngine.load(base=policy_file(profile)).version
    if profile == "default":
        return "" if version == "2" else f"__policy-v{version}"
    return f"__policy-{profile}-v{version}"


def out_path(suite: str, condition: str, mode: str, trust: str, tag: str, policy: str = "default") -> Path:
    name = (f"{suite}__{condition}{'__strict' if trust == 'strict' else ''}__{mode}"
            f"{policy_suffix(condition, policy)}{'__' + tag if tag else ''}.jsonl")
    return RAW / name


def run_one(suite, condition, settings, mapping, trust, policy, pricing, user_task, injection_task, injections):
    built = build_pipeline(condition, suite.name, settings, mapping, trust, policy)
    start = time.perf_counter()
    error = None
    try:
        utility, security = suite.run_task_with_pipeline(built.pipeline, user_task, injection_task=injection_task,
                                                         injections=injections)
    except Exception as exc:  # recorded, not hidden
        utility, security, error = False, False, f"{type(exc).__name__}: {exc}"[:500]
        logging.debug(traceback.format_exc())
    seconds = time.perf_counter() - start
    u = built.client.usage
    super_cost = pricing.cost(settings.models["super"], u.tokens_in, u.tokens_out) or 0.0
    record = {
        "suite": suite.name, "condition": condition, "trust": trust, "mapping_version": mapping["version"],
        "user_task": user_task.ID, "injection_task": injection_task.ID if injection_task else None,
        "utility": bool(utility), "attack_success": bool(security) if injection_task else None,
        "seconds": round(seconds, 2), "error": error,
        "planner": {"calls": u.calls, "tokens_in": u.tokens_in, "tokens_out": u.tokens_out,
                    "seconds": round(u.seconds, 2), "cost_usd": super_cost},
    }
    if built.router is not None:
        summary = built.router.usage_summary()
        record["tripwire"] = {t: {k: v[k] for k in ("calls", "tokens_in", "tokens_out", "cost_usd")}
                              for t, v in summary["tiers"].items()}
        record["tripwire_seconds"] = round(sum(r.latency_ms for r in built.router.records) / 1000, 2)
        record["policy"] = built.executor.policy
        trace = built.executor.trace
        record.update(decisions=trace.decisions, held=trace.held, blocked=trace.blocked,
                      reader_calls=trace.reader_calls)
        tw_cost = summary["total_cost_usd"]
    else:
        tw_cost = 0.0
    record["cost_usd"] = round(super_cost + tw_cost, 6)
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", required=True, choices=["slack", "banking", "travel"])
    ap.add_argument("--condition", required=True, choices=CONDITIONS)
    ap.add_argument("--mode", required=True, choices=["utility", "attack"])
    ap.add_argument("--trust", default="team", choices=["team", "strict"])
    ap.add_argument("--limit", type=int, default=None, help="only the first N runs (dry runs)")
    ap.add_argument("--tag", default="", help="suffix for the output file, e.g. dry")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--policy", default="default", choices=["default", "strict"])
    args = ap.parse_args()
    if args.trust == "strict" and not args.condition.startswith("tripwire"):
        ap.error("--trust strict only applies to Tripwire conditions")

    logging.basicConfig(level=logging.WARNING)
    for noisy in ("httpx", "openai", "agentdojo"):
        logging.getLogger(noisy).setLevel(logging.ERROR)

    settings = Settings.from_env(ROOT / ".env")
    mapping = load_mapping()
    suite = get_suite(BENCHMARK_VERSION, args.suite)
    check_mapping(mapping, args.suite, [t.name for t in suite.tools])
    pricing = Pricing.from_file(ROOT / "config" / "pricing.yaml")

    jobs = []
    if args.mode == "utility":
        jobs = [(ut, None, {}) for ut in suite.user_tasks.values()]
    else:
        attack = load_attack(ATTACK, suite, build_pipeline("none", args.suite, settings, mapping).pipeline)
        for ut in suite.user_tasks.values():
            for it in suite.injection_tasks.values():
                jobs.append((ut, it, attack.attack(ut, it)))
    if args.limit:
        jobs = jobs[: args.limit]

    path = out_path(args.suite, args.condition, args.mode, args.trust, args.tag, args.policy)
    path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if path.exists():
        for line in path.read_text().splitlines():
            r = json.loads(line)
            if not r.get("error"):
                done.add((r["user_task"], r["injection_task"]))
    jobs = [j for j in jobs if (j[0].ID, j[1].ID if j[1] else None) not in done]
    print(f"{args.suite}/{args.condition}/{args.mode}/{args.trust}: {len(jobs)} runs to do, {len(done)} already done")

    lock = threading.Lock()
    total_cost = 0.0
    with ThreadPoolExecutor(max_workers=args.workers) as pool, path.open("a") as out:
        futures = [pool.submit(run_one, suite, args.condition, settings, mapping, args.trust, args.policy, pricing, *j)
                   for j in jobs]
        for i, fut in enumerate(as_completed(futures), 1):
            rec = fut.result()
            with lock:
                out.write(json.dumps(rec) + "\n")
                out.flush()
                total_cost += rec["cost_usd"]
            flag = "ERR" if rec["error"] else ("U" if rec["utility"] else "-") + (
                "A" if rec["attack_success"] else "" if rec["attack_success"] is None else ".")
            print(f"[{i}/{len(jobs)}] {rec['user_task']:>14} {str(rec['injection_task']):>18} {flag:<3} "
                  f"${rec['cost_usd']:.4f} {rec['seconds']:.1f}s", flush=True)
    print(f"done: {len(jobs)} runs, ${total_cost:.4f}, written to {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
