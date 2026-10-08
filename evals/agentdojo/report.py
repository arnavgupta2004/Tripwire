"""Aggregate AgentDojo results into results.json, results.md and charts.

  uv run --group eval python evals/agentdojo/report.py
"""

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
RAW = HERE / "results" / "raw"
OUT = HERE / "results"
SUITES = ("slack", "banking", "travel")
# Slack and Banking informed the policy (v2 was built on them, v3's change was argued
# from a demo case and checked on them), so they are development suites. Travel was
# never run before policy v3 and its mapping were frozen: it is held out.
SUITE_ROLE = {"slack": "development", "banking": "development", "travel": "held-out"}
# (condition, trust domain, policy file suffix, label). v2 runs keep their original files.
CONDITIONS = [("none", "team", "", "No defense"), ("spotlighting", "team", "", "Spotlighting"),
              ("tripwire_gw", "team", "", "Tripwire (gateway, v2)"), ("tripwire_full", "team", "", "Tripwire (full, v2)"),
              ("tripwire_full", "strict", "", "Tripwire (full, v2, strict trust)"),
              ("tripwire_gw", "team", "__policy-v3", "Tripwire (gateway, v3)"),
              ("tripwire_full", "team", "__policy-v3", "Tripwire (full, v3)")]


def cond_key(condition: str, trust: str, policy: str) -> str:
    return f"{condition}{'__strict' if trust == 'strict' else ''}{policy.replace('__policy-', '__')}"


def load(suite: str, condition: str, mode: str, trust: str = "team", policy: str = "") -> list[dict]:
    path = RAW / f"{suite}__{condition}{'__strict' if trust == 'strict' else ''}__{mode}{policy}.jsonl"
    if not path.exists():
        return []
    rows: dict[tuple, dict] = {}
    for line in path.read_text().splitlines():
        r = json.loads(line)
        if not r.get("error"):
            rows[(r["user_task"], r["injection_task"])] = r  # last clean record wins
    return list(rows.values())


def rate(rows: list[dict], key: str) -> float | None:
    vals = [bool(r[key]) for r in rows]
    return sum(vals) / len(vals) if vals else None


def mean(xs: list[float]) -> float | None:
    return statistics.fmean(xs) if xs else None


def median(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


def stop_category(r: dict) -> str:
    """Why a Tripwire run did not complete the user's task."""
    if r.get("blocked"):
        return "blocked by policy"
    if r.get("held"):
        return "held for approval (counted as not completed)"
    return "no gateway stop (planner or reader)"


def first_stop(r: dict) -> str | None:
    for d in r.get("decisions", []):
        if d["verdict"] != "ALLOW":
            return d["rule"]
    return None


def summarize() -> dict:
    out: dict = {}
    for suite in SUITES:
        base_u = {r["user_task"]: r for r in load(suite, "none", "utility")}
        base_a = {(r["user_task"], r["injection_task"]): r for r in load(suite, "none", "attack")}
        # Medians: occasional Token Factory request stalls add minutes to a run and swamp means.
        base_lat_u = median([r["seconds"] for r in base_u.values()])
        base_lat_a = median([r["seconds"] for r in base_a.values()])
        suite_out = {}
        for condition, trust, policy, label in CONDITIONS:
            util = load(suite, condition, "utility", trust, policy)
            att = load(suite, condition, "attack", trust, policy)
            if not util and not att:
                continue
            if trust == "strict" and not util:
                util_rows = []
            else:
                util_rows = util
            entry = {
                "label": label, "condition": condition, "trust": trust,
                "policy": "v3" if policy else ("v2" if condition.startswith("tripwire") else None),
                "n_utility": len(util_rows), "n_attack": len(att),
                "benign_utility": rate(util_rows, "utility"),
                "utility_under_attack": rate(att, "utility"),
                "asr": rate(att, "attack_success"),
                "latency_s_utility": median([r["seconds"] for r in util_rows]),
                "latency_s_attack": median([r["seconds"] for r in att]),
                "cost_usd_per_task_utility": mean([r["cost_usd"] for r in util_rows]),
                "cost_usd_per_task_attack": mean([r["cost_usd"] for r in att]),
            }
            if base_lat_u and entry["latency_s_utility"] is not None:
                entry["added_latency_s_utility"] = entry["latency_s_utility"] - base_lat_u
            if base_lat_a and entry["latency_s_attack"] is not None:
                entry["added_latency_s_attack"] = entry["latency_s_attack"] - base_lat_a
            if condition.startswith("tripwire"):
                failed = [r for r in util_rows if not r["utility"] and base_u.get(r["user_task"], {}).get("utility")]
                entry["benign_failures_vs_none"] = dict(Counter(stop_category(r) for r in failed))
                entry["benign_tasks_with_hold"] = sum(1 for r in util_rows if r.get("held"))
                stopped = [r for r in att if not r["attack_success"]
                           and base_a.get((r["user_task"], r["injection_task"]), {}).get("attack_success")]
                entry["attacks_stopped_that_beat_none"] = len(stopped)
                entry["stopping_rule"] = dict(Counter(first_stop(r) or "no gateway stop" for r in stopped))
                entry["tripwire_calls_per_task"] = mean([
                    sum(t["calls"] for t in r.get("tripwire", {}).values()) for r in att]) if att else None
            by_injection = defaultdict(list)
            for r in att:
                by_injection[r["injection_task"]].append(r["attack_success"])
            entry["asr_by_injection_task"] = {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by_injection.items())}
            suite_out[cond_key(condition, trust, policy)] = entry
        if suite_out:
            out[suite] = {"role": SUITE_ROLE[suite], **suite_out}
    return out


def pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.1f}%"


def secs(x: float | None) -> str:
    return "–" if x is None else f"{x:+.1f}s"


def money(x: float | None) -> str:
    return "–" if x is None else f"${x:.4f}"


def chart(summary: dict, metric: str, title: str, filename: str) -> None:
    labels = [label for *_, label in CONDITIONS]
    fig, ax = plt.subplots(figsize=(12, 4.6))
    suites = [s for s in SUITES if s in summary]
    width = 0.8 / len(suites)
    for i, suite in enumerate(suites):
        vals: list[float | None] = []
        for condition, trust, policy, _ in CONDITIONS:
            e = summary.get(suite, {}).get(cond_key(condition, trust, policy))
            v = e.get(metric) if e else None
            if e and metric == "benign_utility" and not e.get("n_utility"):
                v = None  # the strict variant was only run on attacked tasks
            vals.append(None if v is None else 100 * v)
        xs = [x + (i - (len(suites) - 1) / 2) * width for x in range(len(labels))]
        bars = ax.bar(xs, [0 if v is None else v for v in vals], width,
                      label=f"{suite.title()} ({SUITE_ROLE[suite]})", color=["#3b6fb6", "#d98c2b", "#3b8f5a"][i])
        for b, v in zip(bars, vals):
            text = "not run" if v is None else f"{v:.0f}%"
            ax.text(b.get_x() + b.get_width() / 2, (0 if v is None else v) + 1, text, ha="center",
                    fontsize=7 if v is None else 8, color="#777" if v is None else "black")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=14, fontsize=8, ha="right")
    ax.set_ylim(0, 105)
    ax.set_ylabel("%")
    ax.set_title(title)
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / filename, dpi=160)
    plt.close(fig)


def table(summary: dict) -> str:
    lines = []
    for suite in SUITES:
        rows = {k: v for k, v in summary.get(suite, {}).items() if k != "role"}
        if not rows:
            continue
        lines += [f"### {suite.title()} ({SUITE_ROLE[suite]})", "",
                  "| Condition | Strict utility (benign) | Strict utility under attack | Targeted ASR | Added median latency / task (benign, attacked) | Mean cost / task (benign, attacked) |",
                  "|---|---|---|---|---|---|"]
        for key, e in rows.items():
            lines.append(
                f"| {e['label']} | {pct(e['benign_utility'])} ({e['n_utility']}) | {pct(e['utility_under_attack'])} | "
                f"{pct(e['asr'])} ({e['n_attack']}) | {secs(e.get('added_latency_s_utility'))}, "
                f"{secs(e.get('added_latency_s_attack'))} | {money(e['cost_usd_per_task_utility'])}, "
                f"{money(e['cost_usd_per_task_attack'])} |")
        lines.append("")
    return "\n".join(lines)


BREAKDOWN_CONDITIONS = [("none", "", "No defense"), ("spotlighting", "", "Spotlighting"),
                        ("tripwire_gw", "", "Tripwire (gateway, v2)"), ("tripwire_full", "", "Tripwire (full, v2)"),
                        ("tripwire_gw", "__policy-v3", "Tripwire (gateway, v3)"),
                        ("tripwire_full", "__policy-v3", "Tripwire (full, v3)")]
CATEGORIES = ["completed", "held", "hard_blocked", "reader_dropped", "other"]
CATEGORY_LABELS = {"completed": "Completed", "held": "Held for approval", "hard_blocked": "Hard blocked",
                   "reader_dropped": "Reader dropped detail", "other": "Other"}


def classify(r: dict, gw_completed: set[str], condition: str) -> str:
    """Why a benign run did or didn't complete. Order matters: a run with any hard
    block can't be rescued by approving a held action."""
    if r["utility"]:
        return "completed"
    verdicts = [d["verdict"] for d in r.get("decisions", [])]
    if "BLOCK" in verdicts:
        return "hard_blocked"
    if "NEEDS_APPROVAL" in verdicts:
        return "held"
    if condition == "tripwire_full" and r["user_task"] in gw_completed:
        return "reader_dropped"
    return "other"


def breakdown() -> dict:
    """Benign-run outcome categories per suite and condition, plus effective utility."""
    out: dict = {}
    for suite in SUITES:
        out[suite] = {}
        for condition, policy, label in BREAKDOWN_CONDITIONS:
            gw_completed = {r["user_task"] for r in load(suite, "tripwire_gw", "utility", "team", policy) if r["utility"]}
            rows = load(suite, condition, "utility", "team", policy)
            if not rows:
                continue
            counts = Counter(classify(r, gw_completed, condition) for r in rows)
            examples: dict[str, list[str]] = defaultdict(list)
            for r in rows:
                examples[classify(r, gw_completed, condition)].append(r["user_task"])
            n = len(rows)
            out[suite][cond_key(condition, "team", policy)] = {
                "label": label, "n": n, **{c: counts.get(c, 0) for c in CATEGORIES},
                "strict_utility": counts.get("completed", 0) / n,
                "effective_utility": (counts.get("completed", 0) + counts.get("held", 0)) / n,
                "tasks": {c: sorted(v, key=lambda t: int(t.split("_")[-1])) for c, v in examples.items()
                          if c != "completed"},
            }
        if not out[suite]:
            del out[suite]
    return out


def breakdown_table(b: dict) -> str:
    lines = ["| Suite | Condition | Completed | Held for approval | Hard blocked | Reader dropped detail | Other "
             "| Strict utility | Effective utility |", "|---|---|---|---|---|---|---|---|---|"]
    for suite, rows in b.items():
        for e in rows.values():
            lines.append(f"| {suite.title()} | {e['label']} | {e['completed']} | {e['held']} | {e['hard_blocked']} | "
                         f"{e['reader_dropped']} | {e['other']} | {pct(e['strict_utility'])} | "
                         f"{pct(e['effective_utility'])} |")
    return "\n".join(lines)


def breakdown_chart(b: dict) -> None:
    colors = {"completed": "#3b8f5a", "held": "#e3b341", "hard_blocked": "#c94c4c",
              "reader_dropped": "#7d68b5", "other": "#9aa0a6"}
    bars = [(f"{suite.title()}\n{e['label']}", e) for suite, rows in b.items() for e in rows.values()]
    fig, ax = plt.subplots(figsize=(max(11, 0.9 * len(bars)), 4.8))
    xs = range(len(bars))
    bottoms = [0.0] * len(bars)
    for cat in CATEGORIES:
        vals = [100 * e[cat] / e["n"] for _, e in bars]
        ax.bar(xs, vals, 0.62, bottom=bottoms, color=colors[cat], label=CATEGORY_LABELS[cat])
        for x, v, b0 in zip(xs, vals, bottoms):
            if v >= 6:
                ax.text(x, b0 + v / 2, f"{v:.0f}%", ha="center", va="center", fontsize=7, color="white")
        bottoms = [b0 + v for b0, v in zip(bottoms, vals)]
    ax.set_xticks(list(xs))
    ax.set_xticklabels([name for name, _ in bars], fontsize=7, rotation=30, ha="right")
    ax.set_ylim(0, 100)
    ax.set_ylabel("% of benign tasks")
    ax.set_title("What happened to each benign task")
    ax.legend(frameon=False, fontsize=8, ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.16))
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "benign_outcomes.png", dpi=160)
    plt.close(fig)


def main() -> None:
    summary = summarize()
    (OUT / "results.json").write_text(json.dumps(summary, indent=2))
    b = breakdown()
    (OUT / "benign_breakdown.json").write_text(json.dumps(b, indent=2))
    breakdown_chart(b)
    print(breakdown_table(b))
    for suite, rows in b.items():
        for cond, e in rows.items():
            print(suite, cond, e["tasks"])
    chart(summary, "asr", "Targeted attack success rate (lower is better)", "asr_by_condition.png")
    chart(summary, "benign_utility", "Strict benign utility: held = not completed (higher is better)", "utility_by_condition.png")
    chart(summary, "utility_under_attack", "Strict utility under attack (higher is better)", "utility_under_attack.png")
    print(table(summary))
    for suite, rows in summary.items():
        for key, e in rows.items():
            if isinstance(e, dict) and "stopping_rule" in e:
                print(suite, key, "benign failures:", e["benign_failures_vs_none"], "| stopped by:", e["stopping_rule"])


if __name__ == "__main__":
    main()
