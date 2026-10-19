import { NavLink } from "react-router-dom";
import type { NavItem } from "../lib/nav";
import { StockPicker } from "./StockPicker";

export function SubNav({ items }: { items: NavItem[] }) {
  return (
    <nav className="subnav" aria-label="Section">
      {items.map((s) => <NavLink key={s.to} to={s.to} end className={({ isActive }) => (isActive ? "active" : "")}>{s.label}</NavLink>)}
    </nav>
  );
}

// Stock picker fed by the watchlist, used wherever a page works on one stock
// it already has prices for. Type a ticker or a company name.
export function SymbolSelect({ id, value, onChange, symbols, label = "Stock" }: { id: string; value: string; onChange: (v: string) => void; symbols: string[]; label?: string }) {
  return <StockPicker id={id} label={label} value={value} onChange={onChange} placeholder="Search your watchlist" options={symbols.map((symbol) => ({ symbol, name: "" }))} />;
}

// Button that starts a background job and shows its log until it finishes.
import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { toast } from "./Toast";
export function Job({ label, start, status, primary, onDone, disabled, className }: { label: string; start: string; status: string; primary?: boolean; onDone?: () => void; disabled?: boolean; className?: string }) {
  const qc = useQueryClient();
  const st = useQuery({ queryKey: [status], queryFn: () => api.get<{ running: boolean; log?: string[] }>(status), refetchInterval: (q) => (q.state.data?.running ? 2000 : false) });
  const go = useMutation({ mutationFn: () => api.post(start), meta: { ok: `${label} started` }, onSuccess: () => qc.invalidateQueries({ queryKey: [status] }) });
  const was = useRef(false);
  useEffect(() => { const r = !!st.data?.running; if (was.current && !r) { qc.invalidateQueries(); toast(`${label} finished`); onDone?.(); } was.current = r; }, [st.data?.running, qc, onDone, label]);
  const running = !!st.data?.running;
  return (
    <div className={className}>
      <button className={`btn ${primary ? "btn--primary" : ""}`} disabled={disabled || running || go.isPending} onClick={() => go.mutate()}>{running ? "Running" : label}</button>
      {go.isError && <div className="note loss" style={{ marginTop: 6 }}>{(go.error as Error).message}</div>}
      {(running || (st.data?.log?.length ?? 0) > 0) && <pre className="log">{(st.data?.log ?? []).join("\n") || "Starting"}</pre>}
    </div>
  );
}
