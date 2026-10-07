import type { ReactNode } from "react";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export function Button({
  children, onClick, variant = "default", size = "md", disabled, title, className, type,
}: {
  children: ReactNode; onClick?: () => void; variant?: "default" | "primary" | "ghost" | "danger";
  size?: "sm" | "md"; disabled?: boolean; title?: string; className?: string; type?: "button" | "submit";
}) {
  const base = "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition " +
    "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50 disabled:opacity-40 disabled:cursor-not-allowed";
  const sizes = { sm: "text-xs px-2.5 py-1.5", md: "text-sm px-3.5 py-2" };
  const variants = {
    default: "bg-surface-raised text-ink border border-line hover:bg-surface-sunken",
    primary: "bg-brand text-white hover:opacity-90 border border-transparent",
    ghost: "text-ink-soft hover:text-ink hover:bg-surface-sunken border border-transparent",
    danger: "bg-danger text-white hover:opacity-90 border border-transparent",
  };
  return (
    <button type={type || "button"} onClick={onClick} disabled={disabled} title={title}
            className={cx(base, sizes[size], variants[variant], className)}>
      {children}
    </button>
  );
}

const FLOW: Record<string, string> = {
  trusted: "bg-trusted/15 text-trusted border-trusted/30",
  untrusted: "bg-untrusted/15 text-untrusted border-untrusted/30",
  private: "bg-private/15 text-private border-private/30",
  danger: "bg-danger/15 text-danger border-danger/30",
  brand: "bg-brand/10 text-brand border-brand/25",
  neutral: "bg-surface-sunken text-ink-soft border-line",
};

export function Chip({ tone = "neutral", children, mono, title }: {
  tone?: keyof typeof FLOW; children: ReactNode; mono?: boolean; title?: string;
}) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs",
      FLOW[tone], mono && "font-mono")}>
      {children}
    </span>
  );
}

export function EmptyState({ icon, title, hint }: { icon?: ReactNode; title: string; hint?: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-ink-faint">
      {icon && <div className="text-3xl opacity-60">{icon}</div>}
      <p className="text-sm font-medium text-ink-soft">{title}</p>
      {hint && <p className="max-w-xs text-xs">{hint}</p>}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-ink-faint">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-line border-t-brand" />
      {label}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <p className="text-sm text-danger">{message}</p>
      {onRetry && <Button size="sm" onClick={onRetry}>Try again</Button>}
    </div>
  );
}
