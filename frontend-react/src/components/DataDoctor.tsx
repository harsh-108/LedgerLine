import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { base, exchange } from "../lib/format";
import { Card, ErrorBox, Pill } from "./ui";
import { Job } from "./Section";
import { toast } from "./Toast";
import { confirmDialog } from "./Confirm";

/* eslint-disable @typescript-eslint/no-explicit-any */
const STATUS: Record<string, { label: string; kind?: "gain" | "loss" | "guide"; why: string }> = {
  empty: { label: "No data", kind: "loss", why: "No prices stored at all. Repair downloads them, trying the other exchange if this one has none." },
  broken: { label: "Too little", kind: "loss", why: "Under 30 days of prices: charts, signals and backtests cannot run. Repair re-downloads the full history." },
  thin: { label: "Thin", kind: "guide", why: "Under a year of prices. Usually a recent listing. Most tools work; backtests and 200-day averages need more." },
  stale: { label: "Out of date", kind: "guide", why: "The newest price is over a week old. A data refresh normally fixes this; if not, the stock may be suspended or renamed." },
};

export function DataDoctor() {
  const qc = useQueryClient();
  const r = useQuery({ queryKey: ["doctor"], queryFn: () => api.get<any>("/api/doctor/report") });
  const scan = async () => {
    const res = await r.refetch();
    const d = res.data;
    if (d) toast(`Scan finished: ${d.checked} checked, ${d.checked - d.healthy} need${d.checked - d.healthy === 1 ? "s" : ""} a look`);
  };
  const repairOne = useMutation({ mutationFn: (sym: string) => api.post(`/api/doctor/repair?symbol=${encodeURIComponent(sym)}`), meta: { ok: (_r: unknown, s: any) => `Repairing ${base(s)}` }, onSuccess: () => qc.invalidateQueries({ queryKey: ["/api/doctor/status"] }) });
  const dedupe = useMutation({ mutationFn: () => api.post<{ removed: number }>("/api/doctor/dedupe"), meta: { ok: (x: any) => `${x.removed} repeated row${x.removed === 1 ? "" : "s"} removed` }, onSuccess: () => { r.refetch(); qc.invalidateQueries({ queryKey: ["watchlist"] }); } });
  const drop = useMutation({ mutationFn: (x: { id: number; symbol: string }) => api.del(`/api/watchlist/${x.id}`), meta: { ok: (_r: unknown, x: any) => `${x.symbol} removed from your watchlist` }, onSuccess: () => { r.refetch(); qc.invalidateQueries({ queryKey: ["watchlist"] }); } });
  const d = r.data;
  const bad: any[] = (d?.symbols ?? []).filter((s: any) => s.status !== "ok");
  const bySym: Record<string, any> = Object.fromEntries((d?.symbols ?? []).map((s: any) => [s.symbol, s]));
  const issues = bad.length + (d?.duplicates?.length ?? 0) + (d?.both_exchanges?.length ?? 0);

  return (
    <Card title="Data doctor" sub="Checks every stock and ETF on your watchlist: how many days of prices are stored and how recent the newest one is. It also finds repeated and double-listed entries."
      action={<button className="btn" onClick={scan} disabled={r.isFetching}>{r.isFetching ? "Scanning" : "Scan again"}</button>}>
      {r.isError && <div style={{ marginTop: 12 }}><ErrorBox error={r.error} /></div>}
      {d && (<>
        <div className="doctor-stats">
          <div><b>{d.checked}</b><span>checked</span></div>
          <div><b className="gain">{d.healthy}</b><span>healthy</span></div>
          <div><b className={d.broken ? "loss" : undefined}>{d.broken}</b><span>under 30 days of prices</span></div>
          <div><b>{d.thin}</b><span>under a year</span></div>
          <div><b>{d.stale}</b><span>out of date</span></div>
        </div>
        <p className="note" style={{ margin: "10px 0 0" }}>Last scan {String(d.scanned_at).replace("T", " at ")}. {issues === 0 ? "Nothing needs attention." : `${issues} thing${issues === 1 ? "" : "s"} to look at below.`}</p>

        {bad.length > 0 && (
          <div className="table-wrap" style={{ marginTop: 14, marginInline: -20 }}><table className="table">
            <thead><tr><th>Symbol</th><th>Problem</th><th className="right">Days of prices</th><th>Newest price</th><th>Source</th><th className="right"><span className="sr-only">Fix</span></th></tr></thead>
            <tbody>{bad.map((s) => (<tr key={s.symbol}>
              <td className="name"><Link to={`/stocks/${encodeURIComponent(s.symbol)}`}>{base(s.symbol)}</Link> <span className="pill" style={{ height: 20, fontSize: 11 }}>{exchange(s.symbol) || s.symbol}</span></td>
              <td style={{ maxWidth: 380, whiteSpace: "normal", padding: "10px 12px" }}><Pill kind={STATUS[s.status]?.kind}>{STATUS[s.status]?.label ?? s.status}</Pill> <span className="secondary" style={{ fontSize: 12.5 }}>{STATUS[s.status]?.why}</span></td>
              <td className="right">{s.rows}</td>
              <td className="secondary">{s.last ? `${s.last}${s.age_days != null ? ` (${s.age_days} day${s.age_days === 1 ? "" : "s"} ago)` : ""}` : "—"}</td>
              <td className="secondary">{s.source ?? "—"}</td>
              <td className="right">{s.status !== "stale" && <button className="btn" style={{ height: 32 }} disabled={repairOne.isPending} onClick={() => repairOne.mutate(s.symbol)}>Repair</button>}</td>
            </tr>))}</tbody>
          </table></div>
        )}

        {(d.duplicates?.length ?? 0) > 0 && (
          <div className="doctor-issue">
            <div><b>Repeated on your watchlist.</b> {d.duplicates.map((x: any) => `${base(x.symbol)} (${x.copies} times)`).join(", ")}. Repeats show up as identical rows in every stock picker.</div>
            <button className="btn" disabled={dedupe.isPending} onClick={async () => { if (await confirmDialog({ title: "Remove repeated rows?", body: <>One row of each stays on your watchlist; only the extra copies go.</>, confirmLabel: "Remove repeats", cancelLabel: "Keep" })) dedupe.mutate(); }}>Remove repeats</button>
          </div>
        )}
        {(d.both_exchanges ?? []).map((x: any) => {
          const listings = x.symbols.map((sym: string) => bySym[sym]).filter(Boolean);
          const keep = [...listings].sort((a: any, b: any) => b.rows - a.rows)[0];
          return (
            <div className="doctor-issue" key={x.company}>
              <div><b>{x.company} is on your watchlist twice,</b> once per exchange: {listings.map((l: any) => `${exchange(l.symbol)} (${l.rows} days of prices)`).join(" and ")}. It is the same company; keeping one avoids two near-identical rows.</div>
              <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>{listings.filter((l: any) => l.symbol !== keep?.symbol).map((l: any) => (
                <button key={l.symbol} className="btn" disabled={drop.isPending} onClick={() => drop.mutate({ id: l.id, symbol: l.symbol })}>Remove the {exchange(l.symbol)} copy</button>
              ))}</span>
            </div>
          );
        })}
      </>)}
      <div className="track-foot">
        <Job className="job--inline" primary label="Repair all" start="/api/doctor/repair" status="/api/doctor/status" onDone={() => r.refetch()} disabled={!d || (d.broken === 0)} />
        <span className="note">{d && d.broken === 0 ? "Nothing to repair: every symbol has at least 30 days of prices. Thin and out-of-date ones fill in with the next data refresh." : "Re-downloads every symbol with under 30 days of prices, and moves it to the other exchange when only that one has history."}</span>
      </div>
    </Card>
  );
}
