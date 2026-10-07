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
SUITES = ("slack", "banking")
CONDITIONS = [("none", "team", "No defense"), ("spotlighting", "team", "Spotlighting"),
              ("tripwire_gw", "team", "Tripwire (gateway)"), ("tripwire_full", "team", "Tripwire (full)"),
              ("tripwire_full", "strict", "Tripwire (full, strict)")]


def load(suite: str, condition: str, mode: str, trust: str = "team") -> list[dict]:
    path = RAW / f"{suite}__{condition}{'__strict' if trust == 'strict' else ''}__{mode}.jsonl"
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
        for condition, trust, label in CONDITIONS:
            util = load(suite, condition, "utility", trust)
            att = load(suite, condition, "attack", trust)
            if not util and not att:
                continue
            if trust == "strict" and not util:
                util_rows = []
            else:
                util_rows = util
            entry = {
                "label": label, "condition": condition, "trust": trust,
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
            suite_out[f"{condition}{'__strict' if trust == 'strict' else ''}"] = entry
        out[suite] = suite_out
    return out


def pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.1f}%"


def secs(x: float | None) -> str:
    return "–" if x is None else f"{x:+.1f}s"


def money(x: float | None) -> str:
    return "–" if x is None else f"${x:.4f}"


def chart(summary: dict, metric: str, title: str, filename: str) -> None:
    labels = [label for _, _, label in CONDITIONS]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    width = 0.38
    for i, suite in enumerate(SUITES):
        vals: list[float | None] = []
        for condition, trust, _ in CONDITIONS:
            e = summary.get(suite, {}).get(f"{condition}{'__strict' if trust == 'strict' else ''}")
            v = e.get(metric) if e else None
            if e and metric == "benign_utility" and not e.get("n_utility"):
                v = None  # the strict variant was only run on attacked tasks
            vals.append(None if v is None else 100 * v)
        xs = [x + (i - 0.5) * width for x in range(len(labels))]
        bars = ax.bar(xs, [0 if v is None else v for v in vals], width, label=suite.title(),
                      color=["#3b6fb6", "#d98c2b"][i])
        for b, v in zip(bars, vals):
            text = "not run" if v is None else f"{v:.0f}%"
            ax.text(b.get_x() + b.get_width() / 2, (0 if v is None else v) + 1, text, ha="center",
                    fontsize=7 if v is None else 8, color="#777" if v is None else "black")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=12, fontsize=9)
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
        rows = summary.get(suite, {})
        if not rows:
            continue
        lines += [f"### {suite.title()}", "",
                  "| Condition | Benign utility | Utility under attack | Targeted ASR | Added median latency / task (benign, attacked) | Mean cost / task (benign, attacked) |",
                  "|---|---|---|---|---|---|"]
        for key, e in rows.items():
            lines.append(
                f"| {e['label']} | {pct(e['benign_utility'])} ({e['n_utility']}) | {pct(e['utility_under_attack'])} | "
                f"{pct(e['asr'])} ({e['n_attack']}) | {secs(e.get('added_latency_s_utility'))}, "
                f"{secs(e.get('added_latency_s_attack'))} | {money(e['cost_usd_per_task_utility'])}, "
                f"{money(e['cost_usd_per_task_attack'])} |")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    summary = summarize()
    (OUT / "results.json").write_text(json.dumps(summary, indent=2))
    chart(summary, "asr", "Targeted attack success rate (lower is better)", "asr_by_condition.png")
    chart(summary, "benign_utility", "Benign utility (higher is better)", "utility_by_condition.png")
    chart(summary, "utility_under_attack", "Utility under attack (higher is better)", "utility_under_attack.png")
    print(table(summary))
    for suite, rows in summary.items():
        for key, e in rows.items():
            if "stopping_rule" in e:
                print(suite, key, "benign failures:", e["benign_failures_vs_none"], "| stopped by:", e["stopping_rule"])


if __name__ == "__main__":
    main()
