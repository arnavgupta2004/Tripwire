import { useState } from "react";
import { useStore } from "../store";
import { Button, cx } from "./ui/primitives";

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
  const { health, theme, toggleTheme, setShield, wsUp } = useStore();
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

      <div className="flex items-center justify-between gap-3 border-b border-line bg-surface-raised px-4 py-2">
        <div className="flex items-center gap-2">
          <span className="text-base font-bold tracking-tight">Tripwire</span>
          <span className={cx("h-1.5 w-1.5 rounded-full", wsUp ? "bg-trusted" : "bg-ink-faint")}
                title={wsUp ? "Live" : "Reconnecting…"} />
        </div>
        <nav className="flex items-center gap-1 overflow-x-auto">
          {TABS.map((t) => (
            <button key={t.id} onClick={() => onNavigate(t.id)}
                    className={cx("whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition",
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

function ShieldIcon({ filled }: { filled: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill={filled ? "currentColor" : "none"} stroke="currentColor"
         strokeWidth="1.5">
      <path d="M8 1 2 3.5v4C2 11 4.5 13.6 8 15c3.5-1.4 6-4 6-7.5v-4L8 1Z" />
    </svg>
  );
}
