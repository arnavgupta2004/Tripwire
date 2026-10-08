import { useState } from "react";
import { useStore } from "../store";
import { Button, cx } from "./ui/primitives";
import type { SecurityLevel } from "../types";

export type Screen = "assistant" | "memory" | "routines" | "evidence";
const TABS: { id: Screen; label: string }[] = [
  { id: "assistant", label: "Assistant" },
  { id: "memory", label: "Memory" },
  { id: "routines", label: "Routines" },
  { id: "evidence", label: "Evidence" },
];

function UsageMeter() {
  const { usage } = useStore();
  const tiers = usage?.tiers;
  return (
    <div className="hidden items-center gap-3 rounded-lg border border-line bg-surface-raised px-3 py-1.5 text-xs md:flex"
         title="Nemotron calls and cost this session">
      {(["nano", "super", "ultra"] as const).map((t) => (
        <span key={t} className="flex items-center gap-1 font-mono">
          <span className="capitalize text-ink-faint">{t}</span>
          <span className="text-ink">{tiers ? tiers[t].calls : 0}</span>
        </span>
      ))}
      <span className="font-mono text-brand">${(usage?.total_cost_usd ?? 0).toFixed(4)}</span>
    </div>
  );
}

export function Header({ screen, onNavigate }: { screen: Screen; onNavigate: (s: Screen) => void }) {
  const { health, theme, toggleTheme, setShield, setSecurity, wsUp } = useStore();
  const [busy, setBusy] = useState(false);
  const protectedMode = health?.mode !== "naive";
  const demo = health?.demo_mode;

  const switchMode = async () => {
    setBusy(true);
    await setShield(!protectedMode);
    setBusy(false);
  };

  return (
    <header>
      <div className={cx("flex items-center justify-between px-4 py-1.5 text-xs font-semibold text-white transition-colors",
        protectedMode ? "bg-brand" : "bg-danger")}>
        <span className="flex items-center gap-2">
          <ShieldIcon filled={protectedMode} />
          {protectedMode ? "Protected by Tripwire" : "Naive agent — no Tripwire"}
        </span>
        {demo && (
          <button onClick={switchMode} disabled={busy}
                  className="rounded-md bg-white/20 px-2 py-0.5 font-medium hover:bg-white/30 disabled:opacity-50">
            Switch to {protectedMode ? "naive agent" : "Tripwire"}
          </button>
        )}
      </div>

      {protectedMode && health && (
        <SecurityBar level={health.security ?? "standard"} onChange={setSecurity}
                     onEvidence={() => onNavigate("evidence")} />
      )}

      <div className="flex items-center justify-between gap-3 border-b border-line bg-surface-raised px-4 py-2">
        <div className="flex items-center gap-2">
          <span className="text-base font-bold tracking-tight">Tripwire</span>
          {health?.public_demo && (
            <span className="hidden rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-faint sm:inline"
                  title="Fictional demo data only. Nothing is sent anywhere.">public demo</span>
          )}
          <span className={cx("h-1.5 w-1.5 rounded-full", wsUp ? "bg-trusted" : "bg-ink-faint")}
                title={wsUp ? "Live" : "Reconnecting…"} />
        </div>
        <nav className="flex items-center gap-1 overflow-x-auto">
          {TABS.map((t) => (
            <button key={t.id} onClick={() => onNavigate(t.id)} aria-current={screen === t.id ? "page" : undefined}
                    className={cx("whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium",
                      screen === t.id ? "bg-brand-soft text-brand" : "text-ink-soft hover:bg-surface-sunken")}>
              {t.label}
            </button>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <UsageMeter />
          <Button size="sm" variant="ghost" onClick={toggleTheme} title="Toggle theme">
            {theme === "dark" ? "☀" : "☾"}
          </Button>
        </div>
      </div>
    </header>
  );
}

const SECURITY_COPY: Record<SecurityLevel, string> = {
  standard: "The gateway checks every action. Held-out benchmark: 5.0% attack success, 70% of tasks completed.",
  high: "Also screens what web pages can say to the assistant. Stopped every held-out attack, but drops detail more often.",
};

function SecurityBar({ level, onChange, onEvidence }: {
  level: SecurityLevel; onChange: (l: SecurityLevel) => Promise<string | null>; onEvidence: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const pick = async (l: SecurityLevel) => {
    if (l === level) return;
    setBusy(true);
    await onChange(l);
    setBusy(false);
  };
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-brand-soft/40 px-4 py-1.5 text-xs">
      <div role="radiogroup" aria-label="Security level" className="flex rounded-lg border border-line bg-surface-raised p-0.5">
        {(["standard", "high"] as const).map((l) => (
          <button key={l} role="radio" aria-checked={level === l} disabled={busy} onClick={() => pick(l)}
                  className={cx("rounded-md px-2.5 py-0.5 font-medium",
                    level === l ? "bg-brand text-white" : "text-ink-soft hover:bg-surface-sunken")}>
            {l === "standard" ? "Standard" : "High-security"}
          </button>
        ))}
      </div>
      <span className="min-w-0 flex-1 text-ink-soft">
        {SECURITY_COPY[level]}{" "}
        <button onClick={onEvidence} className="text-brand underline">See the numbers</button>
      </span>
    </div>
  );
}

function ShieldIcon({ filled }: { filled: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill={filled ? "currentColor" : "none"} stroke="currentColor"
         strokeWidth="1.5">
      <path d="M8 1 2 3.5v4C2 11 4.5 13.6 8 15c3.5-1.4 6-4 6-7.5v-4L8 1Z" />
    </svg>
  );
}
