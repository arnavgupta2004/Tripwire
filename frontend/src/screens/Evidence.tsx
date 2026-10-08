import { useMemo } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import summary from "../results/agentdojo_summary.json";
import breakdown from "../results/agentdojo_breakdown.json";
import { useStore } from "../store";
import { cssVar } from "../theme";
import { Chip } from "../components/ui/primitives";

type AnyRec = Record<string, any>;
const S = summary as AnyRec;
const B = breakdown as AnyRec;
const SUITE_ORDER = ["slack", "banking", "travel"];
const SUITES = SUITE_ORDER.filter((s) => S[s]);
const title = (s: string) => s[0].toUpperCase() + s.slice(1);
const role = (s: string): string => S[s]?.role ?? "development";
const HELD_OUT = SUITES.filter((s) => role(s) === "held-out");
// The current policy's Tripwire results (v3), falling back to v2 where v3 wasn't run.
const KEYS: Record<string, string[]> = {
  none: ["none"], spotlighting: ["spotlighting"],
  tripwire_gw: ["tripwire_gw__v3", "tripwire_gw"], tripwire_full: ["tripwire_full__v3", "tripwire_full"],
};
const COND_ORDER = ["none", "spotlighting", "tripwire_gw", "tripwire_full"];
const COND_LABEL: Record<string, string> = {
  none: "No defense", spotlighting: "Spotlighting", tripwire_gw: "Tripwire (gateway)", tripwire_full: "Tripwire (full)",
};
const pick = (src: AnyRec, suite: string, cond: string): AnyRec | undefined =>
  KEYS[cond].map((k) => src[suite]?.[k]).find(Boolean);
const pct = (x?: number | null) => (x == null ? "–" : `${(100 * x).toFixed(1)}%`);
const parseFrac = (s: string) => { const [a, b] = s.split("/").map(Number); return b ? (100 * a) / b : 0; };
const COLORS = ["--brand", "--untrusted", "--trusted"];

function Panel({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-surface-raised p-4 shadow-card">
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      {subtitle && <p className="mb-3 mt-0.5 text-xs text-ink-soft">{subtitle}</p>}
      <div className="h-64">{children}</div>
    </section>
  );
}

export function Evidence() {
  const { theme } = useStore();
  const C = useMemo(() => ({
    grid: cssVar("--line"), ink: cssVar("--ink-soft"),
    slack: cssVar("--brand"), banking: cssVar("--untrusted"),
    suites: COLORS.map((c) => cssVar(c)),
    strict: cssVar("--brand"), effective: cssVar("--trusted"),
    cats: { completed: cssVar("--trusted"), held: cssVar("--untrusted"), hard_blocked: cssVar("--danger"),
            reader_dropped: cssVar("--private"), other: cssVar("--ink-faint") },
  }), [theme]);

  const asrData = COND_ORDER.map((c) => ({
    name: COND_LABEL[c],
    ...Object.fromEntries(SUITES.map((su) => {
      const e = pick(S, su, c);
      return [title(su), e ? +(100 * e.asr).toFixed(1) : null];
    })),
  }));

  const utilRows = SUITES.flatMap((su) => ["tripwire_gw", "tripwire_full"].map((c) => {
    const e = pick(B, su, c);
    return e && { name: `${title(su)} · ${c === "tripwire_gw" ? "gw" : "full"}`,
                  Strict: +(100 * e.strict_utility).toFixed(1), Effective: +(100 * e.effective_utility).toFixed(1) };
  })).filter(Boolean) as AnyRec[];

  const catRows = SUITES.flatMap((su) => COND_ORDER.map((c) => {
    const e = pick(B, su, c); if (!e) return null; const n = e.n;
    return { name: `${title(su).slice(0, 5)} · ${COND_LABEL[c].replace("Tripwire ", "")}`,
             Completed: (100 * e.completed) / n, Held: (100 * e.held) / n, Blocked: (100 * e.hard_blocked) / n,
             Reader: (100 * e.reader_dropped) / n, Other: (100 * e.other) / n };
  })).filter(Boolean) as AnyRec[];

  // Policy v2 vs v3 on the development suites (Tripwire full).
  const versionRows = SUITES.filter((su) => S[su]?.tripwire_full && S[su]?.tripwire_full__v3).flatMap((su) => [
    { name: `${title(su)} · v2`, ASR: +(100 * S[su].tripwire_full.asr).toFixed(1),
      Utility: +(100 * S[su].tripwire_full.benign_utility).toFixed(1) },
    { name: `${title(su)} · v3`, ASR: +(100 * S[su].tripwire_full__v3.asr).toFixed(1),
      Utility: +(100 * S[su].tripwire_full__v3.benign_utility).toFixed(1) },
  ]);

  const goalSuite = HELD_OUT[0] ?? "slack";
  const goalNone = S[goalSuite]?.none?.asr_by_injection_task ?? {};
  const goalFull = pick(S, goalSuite, "tripwire_full")?.asr_by_injection_task ?? {};
  const goals = Object.keys(goalNone).map((k, i) => ({
    name: `Goal ${i + 1}`, "No defense": parseFrac(goalNone[k]), "Tripwire (full)": parseFrac(goalFull[k] ?? "0/0"),
  }));
  const headline = SUITES.map((su) => ({
    suite: su, none: S[su]?.none?.asr, full: pick(S, su, "tripwire_full")?.asr,
  }));

  const axis = { tick: { fontSize: 11, fill: C.ink }, stroke: C.grid };
  const tip = { contentStyle: { background: cssVar("--surface-raised"), border: `1px solid ${C.grid}`,
                borderRadius: 10, fontSize: 12, color: cssVar("--ink") } };

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <div>
        <h2 className="text-lg font-bold">Evidence: AgentDojo</h2>
        <p className="mt-1 max-w-3xl text-sm text-ink-soft">
          Tripwire (policy v3) evaluated as a defense on <a className="text-brand underline"
          href="https://github.com/ethz-spylab/agentdojo" target="_blank" rel="noreferrer">AgentDojo</a>, with Nemotron 3
          Super on Token Factory as the agent in every condition and AgentDojo's published{" "}
          <span className="font-mono">important_instructions</span> attack. Slack and Banking are{" "}
          <strong>development suites</strong>: they informed the policy.{" "}
          {HELD_OUT.length > 0 && <>{HELD_OUT.map(title).join(", ")} is <strong>held out</strong>: run once, after
          the policy and its tool mapping were frozen. </>}
          Lower attack success is better; higher utility is better.
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
          {headline.map((h) => (
            <Chip key={h.suite} tone={role(h.suite) === "held-out" ? "brand" : "neutral"}>
              {title(h.suite)} ({role(h.suite)}) {pct(h.none)} → {pct(h.full)} attack success
            </Chip>
          ))}
          <Chip tone="neutral">full write-up: evals/agentdojo/results.md</Chip>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Targeted attack success by condition" subtitle="Share of injection attempts that met the attacker's goal.">
          <ResponsiveContainer>
            <BarChart data={asrData} margin={{ top: 8, right: 8, bottom: 20, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={C.grid} vertical={false} />
              <XAxis dataKey="name" {...axis} interval={0} angle={-12} textAnchor="end" height={48} />
              <YAxis unit="%" domain={[0, 100]} {...axis} />
              <Tooltip {...tip} formatter={(v: any) => `${v?.toFixed(1)}%`} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {SUITES.map((su, i) => (
                <Bar key={su} dataKey={title(su)} name={`${title(su)} (${role(su)})`} fill={C.suites[i]}
                     radius={[4, 4, 0, 0]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="Strict vs effective utility (Tripwire)"
               subtitle="Strict counts a held action as not completed; effective counts it as completed on one-tap approval.">
          <ResponsiveContainer>
            <BarChart data={utilRows} margin={{ top: 8, right: 8, bottom: 20, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={C.grid} vertical={false} />
              <XAxis dataKey="name" {...axis} interval={0} angle={-12} textAnchor="end" height={48} />
              <YAxis unit="%" domain={[0, 100]} {...axis} />
              <Tooltip {...tip} formatter={(v: any) => `${v}%`} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="Strict" fill={C.strict} radius={[4, 4, 0, 0]} />
              <Bar dataKey="Effective" fill={C.effective} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="What happened to each benign task"
               subtitle="Every benign task by outcome. Held actions complete on approval; hard blocks don't.">
          <ResponsiveContainer>
            <BarChart data={catRows} margin={{ top: 8, right: 8, bottom: 28, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={C.grid} vertical={false} />
              <XAxis dataKey="name" {...axis} interval={0} angle={-18} textAnchor="end" height={60} />
              <YAxis unit="%" domain={[0, 100]} {...axis} />
              <Tooltip {...tip} formatter={(v: any) => `${v.toFixed(0)}%`} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="Completed" stackId="a" fill={C.cats.completed} />
              <Bar dataKey="Held" stackId="a" fill={C.cats.held} />
              <Bar dataKey="Blocked" stackId="a" fill={C.cats.hard_blocked} />
              <Bar dataKey="Reader" stackId="a" fill={C.cats.reader_dropped} />
              <Bar dataKey="Other" stackId="a" fill={C.cats.other} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title={`${title(goalSuite)}: attack success per goal`}
               subtitle={`No defense vs Tripwire (full), by the attacker's goal${role(goalSuite) === "held-out" ? " (held-out suite)" : ""}.`}>
          <ResponsiveContainer>
            <BarChart data={goals} margin={{ top: 8, right: 8, bottom: 20, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={C.grid} vertical={false} />
              <XAxis dataKey="name" {...axis} interval={0} />
              <YAxis unit="%" domain={[0, 100]} {...axis} />
              <Tooltip {...tip} formatter={(v: any) => `${v.toFixed(0)}%`} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="No defense" fill={C.banking} radius={[4, 4, 0, 0]} />
              <Bar dataKey="Tripwire (full)" fill={C.slack} radius={[4, 4, 0, 0]}>
                {goals.map((_, i) => <Cell key={i} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Panel>

        {versionRows.length > 0 && (
          <Panel title="Policy v2 vs v3 (development suites, Tripwire full)"
                 subtitle="v3 checks external calls after a private read with the classifier instead of blocking them all.">
            <ResponsiveContainer>
              <BarChart data={versionRows} margin={{ top: 8, right: 8, bottom: 20, left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.grid} vertical={false} />
                <XAxis dataKey="name" {...axis} interval={0} />
                <YAxis unit="%" domain={[0, 100]} {...axis} />
                <Tooltip {...tip} formatter={(v: any) => `${v}%`} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="ASR" name="Attack success" fill={C.cats.hard_blocked} radius={[4, 4, 0, 0]} />
                <Bar dataKey="Utility" name="Strict benign utility" fill={C.cats.completed} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Panel>
        )}
      </div>

      <section className="rounded-2xl border border-line bg-surface-raised p-4 text-sm text-ink-soft shadow-card">
        <h3 className="mb-1 font-semibold text-ink">How to read this</h3>
        <ul className="list-disc space-y-1 pl-5">
          <li>Same model (Nemotron Super) and system message in every condition. Only the defense differs.</li>
          <li>Development suites shaped the policy, so their numbers flatter it; the held-out suite is the honest estimate.</li>
          <li>One run per (task, attack) pair, so single bars are noisy; the comparison across conditions is the signal.</li>
          <li>The reader is a dial: gateway-only gives higher utility, full gives fewer successful attacks.</li>
          <li>Caveats (temperature default, role mapping, trust-domain definition) are in results.md.</li>
        </ul>
      </section>
    </div>
  );
}
