import { useMemo } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import summary from "../data/agentdojo_summary.json";
import breakdown from "../data/agentdojo_breakdown.json";
import { useStore } from "../store";
import { cssVar } from "../theme";
import { Chip } from "../components/ui/primitives";

type AnyRec = Record<string, any>;
const COND_ORDER = ["none", "spotlighting", "tripwire_gw", "tripwire_full"];
const COND_LABEL: Record<string, string> = {
  none: "No defense", spotlighting: "Spotlighting", tripwire_gw: "Tripwire (gateway)", tripwire_full: "Tripwire (full)",
};
const parseFrac = (s: string) => { const [a, b] = s.split("/").map(Number); return b ? (100 * a) / b : 0; };

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
    strict: cssVar("--brand"), effective: cssVar("--trusted"),
    cats: { completed: cssVar("--trusted"), held: cssVar("--untrusted"), hard_blocked: cssVar("--danger"),
            reader_dropped: cssVar("--private"), other: cssVar("--ink-faint") },
  }), [theme]);

  const asrData = COND_ORDER.map((c) => ({
    name: COND_LABEL[c],
    Slack: (summary as AnyRec).slack[c] ? 100 * (summary as AnyRec).slack[c].asr : null,
    Banking: (summary as AnyRec).banking[c] ? 100 * (summary as AnyRec).banking[c].asr : null,
  }));

  const utilRows = (["slack", "banking"] as const).flatMap((suite) =>
    COND_ORDER.filter((c) => c.startsWith("tripwire")).map((c) => {
      const e = (breakdown as AnyRec)[suite][c];
      return { name: `${suite === "slack" ? "Slack" : "Bank"} · ${c === "tripwire_gw" ? "gw" : "full"}`,
               Strict: +(100 * e.strict_utility).toFixed(1), Effective: +(100 * e.effective_utility).toFixed(1) };
    }));

  const catRows = (["slack", "banking"] as const).flatMap((suite) =>
    COND_ORDER.map((c) => {
      const e = (breakdown as AnyRec)[suite][c]; const n = e.n;
      return { name: `${suite === "slack" ? "Slack" : "Bank"} · ${COND_LABEL[c].replace("Tripwire ", "")}`,
               Completed: (100 * e.completed) / n, Held: (100 * e.held) / n, Blocked: (100 * e.hard_blocked) / n,
               Reader: (100 * e.reader_dropped) / n, Other: (100 * e.other) / n };
    }));

  const slackGoals = Object.keys((summary as AnyRec).slack.none.asr_by_injection_task).map((k, i) => ({
    name: `Goal ${i + 1}`,
    "No defense": parseFrac((summary as AnyRec).slack.none.asr_by_injection_task[k]),
    "Tripwire (full)": parseFrac((summary as AnyRec).slack.tripwire_full.asr_by_injection_task[k]),
  }));

  const axis = { tick: { fontSize: 11, fill: C.ink }, stroke: C.grid };
  const tip = { contentStyle: { background: cssVar("--surface-raised"), border: `1px solid ${C.grid}`,
                borderRadius: 10, fontSize: 12, color: cssVar("--ink") } };

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <div>
        <h2 className="text-lg font-bold">Evidence: AgentDojo</h2>
        <p className="mt-1 max-w-3xl text-sm text-ink-soft">
          Tripwire evaluated as a defense on <a className="text-brand underline" href="https://github.com/ethz-spylab/agentdojo"
          target="_blank" rel="noreferrer">AgentDojo</a>'s Slack and Banking suites, with Nemotron 3 Super on Token Factory
          as the agent in every condition and AgentDojo's published <span className="font-mono">important_instructions</span> attack.
          Lower attack success is better; higher utility is better.
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
          <Chip tone="brand">Slack 69.5% → 14.3% attack success</Chip>
          <Chip tone="brand">Banking 25.0% → 0.0%</Chip>
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
              <Bar dataKey="Slack" fill={C.slack} radius={[4, 4, 0, 0]} />
              <Bar dataKey="Banking" fill={C.banking} radius={[4, 4, 0, 0]} />
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

        <Panel title="Slack: attack success per goal" subtitle="No defense vs Tripwire (full), by the attacker's goal.">
          <ResponsiveContainer>
            <BarChart data={slackGoals} margin={{ top: 8, right: 8, bottom: 20, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={C.grid} vertical={false} />
              <XAxis dataKey="name" {...axis} interval={0} />
              <YAxis unit="%" domain={[0, 100]} {...axis} />
              <Tooltip {...tip} formatter={(v: any) => `${v.toFixed(0)}%`} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="No defense" fill={C.banking} radius={[4, 4, 0, 0]} />
              <Bar dataKey="Tripwire (full)" fill={C.slack} radius={[4, 4, 0, 0]}>
                {slackGoals.map((_, i) => <Cell key={i} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Panel>
      </div>

      <section className="rounded-2xl border border-line bg-surface-raised p-4 text-sm text-ink-soft shadow-card">
        <h3 className="mb-1 font-semibold text-ink">How to read this</h3>
        <ul className="list-disc space-y-1 pl-5">
          <li>Same model (Nemotron Super) and system message in every condition. Only the defense differs.</li>
          <li>One run per (task, attack) pair, so single bars are noisy; the comparison across conditions is the signal.</li>
          <li>The reader is a dial: gateway-only gives higher utility, full gives fewer successful attacks.</li>
          <li>Caveats (temperature default, role mapping, trust-domain definition) are in results.md.</li>
        </ul>
      </section>
    </div>
  );
}
