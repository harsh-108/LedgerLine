import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { base, money, signed } from "../lib/format";
import { TIER_LABEL, tierKind } from "../lib/labels";
import { Card, Change, ErrorBox, PageHead, Pill, SkeletonCard, Stat } from "../components/ui";
import { SeriesChart } from "../components/SeriesChart";
import { SubNav } from "../components/Section";
import { PeekLink } from "../components/Peek";
import { PORTFOLIO } from "../lib/nav";
import { toast } from "../components/Toast";
import { Icon } from "../components/Icon";

/* eslint-disable @typescript-eslint/no-explicit-any */
// Yearly return when money went in on different dates (Newton's method).
function xirr(flows: { t: number; v: number }[]): number | null {
  if (flows.length < 2) return null;
  const t0 = flows[0].t; let r = 0.1;
  for (let i = 0; i < 60; i++) {
    let f = 0, df = 0;
    for (const c of flows) { const y = (c.t - t0) / 31557600000; const d = Math.pow(1 + r, y); f += c.v / d; df -= (y * c.v) / (d * (1 + r)); }
    if (Math.abs(df) < 1e-12) break;
    const n = r - f / df; if (!Number.isFinite(n) || n <= -0.99) return null;
    if (Math.abs(n - r) < 1e-7) return n * 100; r = n;
  }
  return r * 100;
}

function exportCsv(rows: any[]) {
  if (!rows.length) { toast("No holdings to export", "err"); return; }
  const cols = ["Symbol", "Qty", "Avg cost", "Last", "Invested", "Current", "P&L", "P&L %", "Since", "thesis"];
  const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const csv = [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = "holdings.csv"; a.click(); URL.revokeObjectURL(a.href);
  toast(`Exported ${rows.length} holdings`);
}

export default function Portfolio() {
  const qc = useQueryClient();
  const p = useQuery({ queryKey: ["portfolio"], staleTime: 5 * 60_000, queryFn: () => api.get<any>("/api/portfolio") });
  const fix = useMutation({
    mutationFn: () => api.post<any>("/api/portfolio/fix-prices"),
    meta: { ok: (r: any) => r?.fixed?.length ? `Prices fetched for ${r.fixed.map((f: any) => base(f.now)).join(", ")}` : "No new prices found" },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["portfolio"] }),
  });
  const series = useMemo(() => {
    const c: any[] = p.data?.curve ?? [];
    return [
      { name: "Portfolio value", color: "--action", data: c.map((x) => ({ time: x.time, value: x.value })) },
      { name: "Amount invested", color: "--slate", dashed: true, data: c.map((x) => ({ time: x.time, value: x.invested })) },
      { name: "NIFTYBEES, same cash flows", color: "--teal", data: c.filter((x) => x.benchmark != null).map((x) => ({ time: x.time, value: x.benchmark })) },
    ];
  }, [p.data]);

  if (p.isLoading) return (<><PageHead title="Portfolio" sub="Fetching the latest prices" /><div className="grid grid-4">{[0, 1, 2, 3].map((i) => <SkeletonCard key={i} lines={2} />)}</div><SkeletonCard lines={8} /></>);
  if (p.isError) return (<><PageHead title="Portfolio" /><ErrorBox error={p.error} /></>);
  const holdings: any[] = p.data.holdings ?? [];
  const totals = p.data.totals;
  const alloc: { label: string; value: number }[] = p.data.allocation ?? [];
  const sectors: { label: string; value: number }[] = p.data.sectors ?? [];
  const maxW = Math.max(1, ...holdings.map((h) => Number(h["Weight %"] ?? 0)));
  const rate = xirr([...holdings.filter((h) => h.Since && h.Invested).map((h) => ({ t: new Date(h.Since).getTime(), v: -h.Invested })).sort((a, b) => a.t - b.t), { t: Date.now(), v: totals?.current ?? 0 }]);
  const priced = holdings.filter((h) => h.Current != null);
  const unpriced = holdings.filter((h) => h.Current == null);
  const maxPnl = Math.max(1, ...priced.map((h) => Math.abs(h["P&L"] ?? 0)));
  const bars = (items: { label: string; value: number }[]) => { const tot = items.reduce((a, b) => a + b.value, 0) || 1; return items.map((s) => (<div key={s.label} style={{ display: "flex", alignItems: "center", gap: 12, height: 32, fontSize: 13.5 }}><span className="secondary" style={{ width: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.label}</span><div className="bar-track"><div className="bar-fill" style={{ width: `${(s.value / tot) * 100}%` }} /></div><span style={{ width: 44, textAlign: "right", fontWeight: 500 }}>{((s.value / tot) * 100).toFixed(0)}%</span></div>)); };

  return (
    <>
      <PageHead title="Portfolio" sub="You add and update holdings yourself. Nothing is synced from a broker."
        actions={<><Link className="btn btn--primary" to="/portfolio/tools"><Icon name="plus" size={16} />Add or sell</Link><button className="btn" onClick={() => exportCsv(holdings)}><Icon name="download" size={16} />Export CSV</button></>} />
      <SubNav items={PORTFOLIO} />
      {totals && holdings.length > 0 && (
        <div className="grid grid-4">
          <div className="card"><Stat big label="Current value" value={money(totals.current, 0)} detail={<span className="muted">{holdings.length} holdings</span>} /></div>
          <div className="card"><Stat big label="You invested" value={money(totals.invested, 0)} detail={rate != null ? <span className="muted">Yearly return (XIRR, approx) <b className={rate >= 0 ? "gain" : "loss"}>{rate.toFixed(1)}%</b></span> : undefined} /></div>
          <div className="card"><Stat big label="Total gain" value={<span className={totals.pnl >= 0 ? "gain" : "loss"}>{signed(totals.pnl)}</span>} detail={<><Change value={totals.pnl_pct} />{totals.dividends ? <span className="muted"> plus {money(totals.dividends, 0)} dividends</span> : null}</>} /></div>
          <div className="card"><Stat big label="Today" value={<Change value={totals.day_pct} />} detail={<span className={totals.day_pnl >= 0 ? "gain" : "loss"}>{signed(totals.day_pnl)}</span>} /></div>
        </div>
      )}
      {holdings.length === 0 ? (
        <Card><div style={{ textAlign: "center", padding: "48px 16px" }}>
          <h2 style={{ fontSize: 24 }}>Add your first holding</h2>
          <p className="secondary" style={{ maxWidth: "52ch", margin: "8px auto 16px", lineHeight: 1.6 }}>Enter what you own, the quantity, and what you paid. Write down why you bought it. The app shows that reason back to you when you sell.</p>
          <Link className="btn btn--primary" to="/portfolio/tools">Add a holding</Link>
        </div></Card>
      ) : (<>
        {unpriced.length > 0 && (
          <div className="callout" style={{ alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", marginBottom: 20 }}>
            <span>{unpriced.length === 1 ? "1 holding has" : `${unpriced.length} holdings have`} no price yet: <b>{unpriced.map((h) => base(h.Symbol)).join(", ")}</b>. Their value is left out of the totals.
              {fix.data?.missing?.length ? <><br />{fix.data.missing.map((m: any) => <span key={m.symbol}><b>{m.symbol}</b>: {m.reason} </span>)}</> : null}</span>
            <button className="btn" disabled={fix.isPending} onClick={() => fix.mutate()}>{fix.isPending ? "Fetching prices" : "Fetch missing prices"}</button>
          </div>
        )}
        {/* Two rows, each pairing cards of similar height, so neither
            column leaves a hole beside the other. */}
        <div className="row">
          <Card className="grow-2" title="Value over time" sub="The gap between value and invested is your gain"><div style={{ marginTop: 12 }}><SeriesChart series={series} height={320} /></div></Card>
          <Card className="grow" title="Allocation"><div style={{ marginTop: 10 }}>{bars(alloc)}</div></Card>
        </div>
        <div className="row">
          <Card className="grow-2" title="Gain by holding"><div style={{ marginTop: 10 }}>{priced.sort((a, b) => (b["P&L"] ?? 0) - (a["P&L"] ?? 0)).map((h) => (<div key={h.Symbol} style={{ display: "flex", alignItems: "center", gap: 12, height: 30, fontSize: 13.5 }}><span className="secondary" style={{ width: 96 }}>{base(h.Symbol)}</span><div className="bar-track"><div className="bar-fill" style={{ width: `${(Math.abs(h["P&L"] ?? 0) / maxPnl) * 100}%`, background: (h["P&L"] ?? 0) >= 0 ? "var(--gain)" : "var(--loss)" }} /></div><span className={(h["P&L"] ?? 0) >= 0 ? "gain" : "loss"} style={{ width: 84, textAlign: "right", fontWeight: 500 }}>{signed(h["P&L"])}</span></div>))}
            {unpriced.length > 0 && <p className="note" style={{ marginBottom: 0 }}>Not shown, no price yet: {unpriced.map((h) => base(h.Symbol)).join(", ")}.</p>}</div></Card>
          <Card className="grow" title="Sector exposure"><div style={{ marginTop: 10 }}>{bars(sectors)}</div></Card>
        </div>
        <Card flush title="Holdings">
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Holding</th><th className="right">Qty</th><th className="right">Avg cost</th><th className="right">Price</th><th className="right">Invested</th><th className="right">Current</th><th className="right">Gain</th><th>Research</th><th>Share of portfolio</th></tr></thead>
            <tbody>
              {holdings.map((h) => (
                <tr key={h.Symbol}>
                  <td className="name"><PeekLink symbol={h.Symbol}>{base(h.Symbol)}</PeekLink><small title={h.thesis ?? ""}>{h.thesis ? String(h.thesis).slice(0, 44) : `Since ${h.Since ?? ""}`}</small></td>
                  <td className="right">{h.Qty}</td><td className="right">{money(h["Avg cost"])}</td><td className="right">{h.Last != null ? money(h.Last) : <span className="muted" style={{ fontSize: 12.5 }}>No price yet</span>}</td>
                  <td className="right">{money(h.Invested, 0)}</td><td className="right"><b style={{ fontWeight: 500 }}>{money(h.Current, 0)}</b></td>
                  <td className="right"><span className={(h["P&L"] ?? 0) >= 0 ? "gain" : "loss"} style={{ fontWeight: 600 }}>{signed(h["P&L"])}</span><div style={{ fontSize: 12.5 }}><Change value={h["P&L %"]} /></div></td>
                  <td>{h.tier ? <Pill kind={tierKind(h.tier)}>{TIER_LABEL[h.tier] ?? h.tier}</Pill> : <span className="muted">&mdash;</span>}</td>
                  <td style={{ minWidth: 140 }}><div style={{ display: "flex", alignItems: "center", gap: 8 }}><div className="bar-track" style={{ height: 6 }}><div className="bar-fill" style={{ height: 6, width: `${(Number(h["Weight %"] ?? 0) / maxW) * 100}%` }} /></div><span style={{ width: 40, textAlign: "right", fontSize: 13 }}>{h["Weight %"] != null ? `${h["Weight %"]}%` : ""}</span></div></td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </Card>
      </>)}
    </>
  );
}
