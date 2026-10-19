import type { ReactNode } from "react";
import { pct, tone } from "../lib/format";
import { Term } from "./InfoTip";

export function PageHead({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="pagehead">
      <div>
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {actions && <div className="pagehead__actions">{actions}</div>}
    </div>
  );
}

export function Card({ title, sub, action, flush, className = "", children }: {
  title?: string; sub?: ReactNode; action?: ReactNode; flush?: boolean; className?: string; children: ReactNode;
}) {
  return (
    <section className={`card ${flush ? "card--flush" : ""} ${className}`}>
      {(title || action) && (
        <div className="card__head">
          <div>
            {title && <h2>{title}</h2>}
            {sub && <div className="sub">{sub}</div>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, detail, big }: { label: string; value: ReactNode; detail?: ReactNode; big?: boolean }) {
  return (
    <div className="stat">
      <div className="k"><Term>{label}</Term></div>
      <div className={`v ${big ? "v--big" : ""}`}>{value}</div>
      {detail && <div className="d">{detail}</div>}
    </div>
  );
}

export function Change({ value, decimals = 2 }: { value: number | null | undefined; decimals?: number }) {
  return <span className={tone(value)} style={{ fontWeight: 500 }}>{pct(value, decimals)}</span>;
}

export function Pill({ children, kind }: { children: ReactNode; kind?: "gain" | "loss" | "guide" | "action" }) {
  return <span className={`pill ${kind ? `pill--${kind}` : ""}`}>{children}</span>;
}

export function Seg<T extends string>({ options, value, onChange, label }: {
  options: readonly T[]; value: T; onChange: (v: T) => void; label: string;
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o} type="button" aria-pressed={o === value} onClick={() => onChange(o)}>{o}</button>
      ))}
    </div>
  );
}

export function Skeleton({ w = "100%", h = 14 }: { w?: string | number; h?: number }) {
  return <div className="sk" style={{ width: w, height: h }} />;
}

export function SkeletonCard({ lines = 4 }: { lines?: number }) {
  return (
    <div className="card" aria-busy="true" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <Skeleton w="40%" h={16} />
      {Array.from({ length: lines }).map((_, i) => <Skeleton key={i} w={`${90 - i * 12}%`} />)}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : "Something went wrong";
  return <div className="error" role="alert">Could not load this. {message}</div>;
}

export function Sparkline({ values, width = 96, height = 30 }: { values: number[]; width?: number; height?: number }) {
  if (!values || values.length < 2) return <span className="muted">&mdash;</span>;
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1, pad = 3;
  const points = values
    .map((v, i) => `${(pad + (i * (width - 2 * pad)) / (values.length - 1)).toFixed(1)},${(height - pad - ((v - lo) / span) * (height - 2 * pad)).toFixed(1)}`)
    .join(" ");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <polyline points={points} fill="none" stroke={up ? "var(--gain)" : "var(--loss)"} strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}
