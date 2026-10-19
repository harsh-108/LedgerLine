import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { getDetail, DETAIL_STALE_MS } from "../lib/detail";
import { base, compact as compactMoney, money, pct, signed } from "../lib/format";
import { useResolvedSymbol } from "../lib/symbols";
import { useSettings } from "../lib/settings";
import type { Evidence, Verdict } from "../lib/types";
import { Card, Change, ErrorBox, Pill, Seg, SkeletonCard, Stat } from "./ui";
import { InfoTip, Term } from "./InfoTip";
import { PriceChart, type Overlays } from "./PriceChart";
import { SeriesChart } from "./SeriesChart";
import { StockNews } from "../pages/Feeds";

/* eslint-disable @typescript-eslint/no-explicit-any */
const RANGES = ["1M", "6M", "1Y", "5Y", "Max"] as const;
const DAYS: Record<(typeof RANGES)[number], number> = { "1M": 22, "6M": 130, "1Y": 252, "5Y": 1260, Max: 1e9 };
const TIER: Record<string, { label: string; cls: string; idx: number }> = { weak: { label: "Sell", cls: "weak", idx: 0 }, mixed: { label: "Hold", cls: "", idx: 1 }, strong: { label: "Buy", cls: "strong", idx: 2 } };
const INDICATORS = ["SMA 50/200", "Volume", "EMA 20", "Bollinger", "MACD", "RSI 14"] as const;
const text = (e: Evidence) => (typeof e === "string" ? e : e.text);
const src = (e: Evidence) => (typeof e === "string" ? undefined : e.source);
const toNum = (s: unknown) => { const n = Number(String(s ?? "").replace(/[^0-9.-]/g, "")); return Number.isFinite(n) ? n : null; };

function VerdictCard({ symbol }: { symbol: string }) {
  const v = useQuery({ queryKey: ["verdict", symbol], staleTime: 5 * 60_000, queryFn: () => api.get<Verdict & { track_record?: any }>(`/api/verdict/${encodeURIComponent(symbol)}`) });
  if (v.isLoading) return <SkeletonCard lines={3} />;
  if (v.isError || !v.data) return null;
  const t = TIER[v.data.tier] ?? TIER.mixed;
  const list = (items: Evidence[]) => (<ul>{items.map((x, i) => <li key={i}>{text(x)}{src(x) && <span className="muted"> ({src(x)})</span>}</li>)}{items.length === 0 && <li>Nothing notable</li>}</ul>);
  const tr = v.data.track_record;
  return (
    <Card>
      <div className="verdict">
        <div className="verdict__tier">
          <div className="muted" style={{ fontSize: 13 }}>The app's call<InfoTip k="__verdict" /></div>
          <div className="t">{t.label}</div>
          <div className="verdict__scale">{[0, 1, 2].map((i) => <span key={i} className={i === t.idx ? `on ${t.cls}` : ""} />)}</div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, marginTop: 4 }} className="muted"><span>Sell</span><span>Hold</span><span>Buy</span></div>
        </div>
        <div className="verdict__col"><h3 className="gain">What supports it</h3>{list(v.data.for)}</div>
        <div className="verdict__col"><h3 className="loss">What argues against</h3>{list(v.data.against)}</div>
      </div>
      <p className="note" style={{ margin: "14px 0 0", borderTop: "1px solid var(--line)", paddingTop: 10 }}>
        {v.data.note}{" "}
        {tr && tr.scored > 0 ? <>Past calls on this stock: {tr.right} right of {tr.scored}. </> : null}
        This call is recorded on the <Link to="/research/scorecard" style={{ textDecoration: "underline" }}>Scorecard</Link>.
      </p>
    </Card>
  );
}

function glance(f: Record<string, any> | null) {
  const out: { topic: string; k: string; word: string; kind: "gain" | "loss" | "guide"; line: string; pos: number }[] = [];
  const n = (k: string) => (typeof f?.[k] === "number" ? (f[k] as number) : null);
  const clamp = (v: number) => Math.max(4, Math.min(96, v));
  const roe = n("returnOnEquity"), de = n("debtToEquity"), pe = n("trailingPE"), margin = n("profitMargins");
  if (pe != null) out.push({ topic: "Valuation", k: "P/E", word: pe > 30 ? "Expensive" : pe < 15 ? "Cheap" : "Moderate", kind: pe > 30 ? "guide" : "gain", line: `Price is ${pe.toFixed(1)} times yearly profit (P/E)`, pos: clamp((pe / 50) * 100) });
  if (roe != null) out.push({ topic: "Profitability", k: "ROE %", word: roe * 100 >= 15 ? "Strong" : "Modest", kind: roe * 100 >= 15 ? "gain" : "guide", line: `Earns ${(roe * 100).toFixed(1)}% on shareholder money (ROE)`, pos: clamp((roe * 100 / 30) * 100) });
  if (de != null) out.push({ topic: "Debt", k: "D/E", word: de <= 50 ? "Low" : de <= 100 ? "Manageable" : "High", kind: de <= 100 ? "gain" : "loss", line: `Owes ${(de / 100).toFixed(2)} for every 1 of its own capital`, pos: clamp((de / 200) * 100) });
  if (margin != null) out.push({ topic: "Margins", k: "", word: margin * 100 >= 8 ? "Healthy" : "Thin", kind: margin * 100 >= 8 ? "gain" : "guide", line: `Keeps ${(margin * 100).toFixed(1)}% of sales as profit`, pos: clamp((margin * 100 / 30) * 100) });
  return out;
}

function Optional({ title, sub, path, render, footer }: { title: string; sub?: string; path: string; render: (d: any) => ReactNode; footer?: ReactNode }) {
  const q = useQuery({ queryKey: [path], queryFn: () => api.get<any>(path), retry: false });
  return (
    <Card title={title} sub={sub}>
      <div style={{ marginTop: 10 }}>
        {q.isLoading && <div className="note">Loading</div>}
        {q.isError && <div className="note">Not available yet. {(q.error as Error).message}</div>}
        {q.data && render(q.data)}
        {footer}
      </div>
    </Card>
  );
}

function Notes({ symbol }: { symbol: string }) {
  const qc = useQueryClient();
  const [t, setT] = useState("");
  const notes = useQuery({ queryKey: ["notes", symbol], queryFn: () => api.get<{ notes: { id: number; text: string; created: string }[] }>(`/api/notes/${encodeURIComponent(symbol)}`) });
  const inval = () => qc.invalidateQueries({ queryKey: ["notes", symbol] });
  const add = useMutation({ mutationFn: () => api.post("/api/notes", { symbol, text: t }), meta: { ok: "Note saved" }, onSuccess: () => { setT(""); inval(); } });
  const del = useMutation({ mutationFn: (id: number) => api.del(`/api/notes/${id}`), meta: { ok: "Note deleted" }, onSuccess: inval });
  const onSubmit = (e: FormEvent) => { e.preventDefault(); if (t.trim()) add.mutate(); };
  return (
    <Card title="Your notes">
      <form onSubmit={onSubmit} className="f" style={{ marginTop: 10 }}>
        <label htmlFor={`note-${symbol}`} className="sr-only">New note</label>
        <textarea id={`note-${symbol}`} rows={3} value={t} onChange={(e) => setT(e.target.value)} placeholder="Why this, why now, and what would change your mind" />
        <button className="btn btn--primary" style={{ marginTop: 8 }} disabled={!t.trim() || add.isPending}>Save note</button>
      </form>
      <div style={{ marginTop: 10 }}>{notes.data?.notes.map((n) => (<div key={n.id} style={{ padding: "10px 0", borderTop: "1px solid var(--line)" }}><div style={{ fontSize: 14, lineHeight: 1.5 }}>{n.text}</div><div className="note" style={{ display: "flex", justifyContent: "space-between" }}><span>{n.created}</span><button className="btn btn--quiet" style={{ height: 24, padding: 0 }} onClick={() => del.mutate(n.id)}>Delete</button></div></div>))}</div>
    </Card>
  );
}

function Shareholding({ symbol }: { symbol: string }) {
  const qc = useQueryClient();
  const path = `/api/shareholding/${encodeURIComponent(symbol)}`;
  const [x, setX] = useState({ quarter: "", promoter: "", pledged: "", fii: "", dii: "" });
  const num = (v: string) => (v === "" ? null : Number(v));
  const save = useMutation({ mutationFn: () => api.post("/api/shareholding", { symbol, quarter: x.quarter, promoter: num(x.promoter), pledged: num(x.pledged), fii: num(x.fii), dii: num(x.dii) }), meta: { ok: "Quarter saved" }, onSuccess: () => { setX({ quarter: "", promoter: "", pledged: "", fii: "", dii: "" }); qc.invalidateQueries({ queryKey: [path] }); } });
  const inp = (k: keyof typeof x, label: string, ph = "") => (<div className="f" style={{ flex: "1 1 80px" }}><label htmlFor={`sh-${k}`}>{label}</label><input id={`sh-${k}`} value={x[k]} onChange={(e) => setX({ ...x, [k]: e.target.value })} placeholder={ph} style={{ height: 38 }} /></div>);
  return (
    <Optional title="Shareholding pattern" sub="No free source is reliable, so you enter four numbers each quarter" path={path}
      render={(d) => (<>
        {(d.notes ?? []).map((n: string, i: number) => <div key={i} className="error" style={{ marginBottom: 8, fontSize: 13 }}>{n}</div>)}
        <div className="table-wrap" style={{ margin: "0 -20px" }}><table className="table"><thead><tr><th>Quarter</th><th className="right">Promoter</th><th className="right">Pledged</th><th className="right">FII</th><th className="right">DII</th></tr></thead>
          <tbody>{(d.series ?? []).slice(-6).map((r: any, i: number) => <tr key={i}><td>{r.quarter}</td><td className="right">{r.promoter ?? "\u2014"}</td><td className="right">{r.pledged ?? "\u2014"}</td><td className="right">{r.fii ?? "\u2014"}</td><td className="right">{r.dii ?? "\u2014"}</td></tr>)}</tbody></table></div>
      </>)}
      footer={<form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} style={{ marginTop: 12 }}><div className="form-row">{inp("quarter", "Quarter", "2026-Q2")}{inp("promoter", "Promoter %")}{inp("pledged", "Pledged %")}{inp("fii", "FII %")}{inp("dii", "DII %")}</div><button className="btn" style={{ marginTop: 10 }} disabled={!x.quarter || save.isPending}>Save quarter</button></form>} />
  );
}

function Research({ symbol, d }: { symbol: string; d: any }) {
  const enc = encodeURIComponent(symbol);
  const [h, setH] = useState<"1m" | "3m" | "6m">("3m");
  const ck = d.checklist, br = d.base_rates;
  const active: string[] = (br?.active ?? []).map((a: any) => (typeof a === "string" ? a : a.signal));
  const rows: { label: string; k: string; s: any; on: boolean }[] = br ? [...(br.signals ?? []).map((s: any) => ({ label: s.label, k: s.label, s: s.horizons?.[h], on: active.includes(s.signal) })), { label: "Any period (baseline)", k: "Any period (baseline)", s: br.baseline?.[h], on: false }] : [];
  return (<>
    <div className="row">
      {ck && (
        <Card className="grow" title="Research checklist" sub={`${ck.passed} of ${ck.applicable} pass. ${ck.tier_text ?? ""}`}>
          <ul style={{ margin: "12px 0 0", paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6, fontSize: 13.5 }}>
            {ck.pros.map((x: string, i: number) => <li key={"p" + i} className="gain"><span className="secondary">{x}</span></li>)}
            {ck.cons.map((x: string, i: number) => <li key={"c" + i} className="loss"><span className="secondary">{x}</span></li>)}
            {ck.notes.map((x: string, i: number) => <li key={"n" + i} className="muted">{x}</li>)}
          </ul>
        </Card>
      )}
      <Card flush className="grow-2" title="What happened historically" sub="Every past time each signal fired on this stock" action={<Seg label="Horizon" options={["1m", "3m", "6m"] as const} value={h} onChange={setH} />}>
        <div className="table-wrap"><table className="table">
          <thead><tr><th>Signal</th><th className="right">Times</th><th className="right"><Term>Median</Term></th><th className="right"><Term>Positive</Term></th><th className="right"><Term>Best</Term></th><th className="right"><Term>Worst</Term></th></tr></thead>
          <tbody>{rows.map((r) => (<tr key={r.label} className={r.on ? "me" : ""}><td>{r.label}<InfoTip k={r.k} />{r.on && <> <Pill kind="guide">Active now</Pill></>}</td><td className="right">{r.s?.n ?? 0}</td><td className="right"><Change value={r.s?.median} decimals={1} /></td><td className="right">{r.s?.hit_rate != null ? `${r.s.hit_rate}%` : "\u2014"}</td><td className="right"><Change value={r.s?.best} decimals={1} /></td><td className="right"><Change value={r.s?.worst} decimals={1} /></td></tr>))}</tbody>
        </table></div>
        {br?.note && <p className="note" style={{ padding: "0 20px 16px", margin: 0 }}>{br.note}</p>}
      </Card>
    </div>
    <div className="masonry">
      <Optional title="Patterns and structure" sub="Candle patterns, this stock's own record" path={`/api/patterns/${enc}`} render={(p) => (<>
        {p.regime && <div className="callout" style={{ marginBottom: 10 }}>{p.regime.read}</div>}
        {(p.candles ?? []).map((c: any) => (<div className="kv" key={c.key}><span>{c.name}<InfoTip k={c.name} />{c.active_today && <> <Pill kind="guide">Today</Pill></>}</span><span>{c.n} times, median {pct(c.median, 1)}</span></div>))}
        {p.structure && <><div className="kv"><span>Nearest support</span><span>{money(p.structure.near_support)}</span></div><div className="kv"><span>Next resistance</span><span>{money(p.structure.next_resistance)}</span></div><div className="kv"><span>Off 52-week high</span><span>{pct(p.structure.off_52w_high_pct, 1)}</span></div></>}
        {p.note && <p className="note">{p.note}</p>}
      </>)} />
      <Optional title="Financials" sub="Revenue and net profit" path={`/api/financials/${enc}`} render={(f) => { const bars = (items: any[]) => { const mx = Math.max(1, ...items.map((x) => Math.max(Math.abs(x.revenue || 0), Math.abs(x.net_income || 0)))); return (<div className="finbars">{items.slice(-6).map((x, i) => (<div key={i} title={x.period}><div className="pair"><i style={{ height: `${(Math.abs(x.revenue || 0) / mx) * 100}%`, background: "var(--action)" }} /><i style={{ height: `${(Math.abs(x.net_income || 0) / mx) * 100}%`, background: (x.net_income || 0) < 0 ? "var(--loss)" : "var(--gain)" }} /></div><span className="muted" style={{ fontSize: 11.5 }}>{String(x.period ?? "").slice(2, 7)}</span></div>))}</div>); }; const b = f.balance?.at?.(-1), c = f.cashflow?.at?.(-1); return (<>
        {f.quarterly?.length > 0 && <><div className="sub">Quarterly</div>{bars(f.quarterly)}<p className="note">Latest quarter margin: {f.quarterly.at(-1).net_margin ?? "\u2014"}%</p></>}
        {f.annual?.length > 0 && <><div className="sub">Annual</div>{bars(f.annual)}</>}
        {b && <><div className="kv"><span>Cash</span><span>{compactMoney(b.cash)}</span></div><div className="kv"><span>Debt</span><span>{compactMoney(b.debt)}</span></div><div className="kv"><span>Equity</span><span>{compactMoney(b.equity)}</span></div></>}
        {c && <><div className="kv"><span>Operating cash flow</span><span>{compactMoney(c.operating)}</span></div><div className="kv"><span>Free cash flow</span><span>{compactMoney(c.free)}</span></div></>}
        <p className="note">Blue is revenue, green is profit. Cross-check with the company's filings before any decision.</p>
      </>); }} />
      <Optional title="Peers" path={`/api/peers/${enc}`} render={(p) => { const seen = new Set<string>(); const rows = (p.rows ?? []).filter((r: any) => { const k = r.symbol; if (seen.has(k) && !r.is_subject) return false; seen.add(k); return true; }).slice(0, 8); return (<>
        <div className="sub" style={{ marginBottom: 8 }}>{p.sector}, median P/E {p.median_pe ?? "\u2014"}</div>
        <div className="table-wrap" style={{ margin: "0 -20px -20px" }}><table className="table"><thead><tr><th>Stock</th><th className="right">Mkt cap, Cr</th><th className="right"><Term>P/E</Term></th><th className="right"><Term>ROE %</Term></th><th className="right">Margin %</th><th className="right">1Y</th></tr></thead>
          <tbody>{rows.map((r: any, i: number) => (<tr key={i} className={r.is_subject ? "me" : ""}><td className="name">{r.symbol}</td><td className="right">{r.mcap_cr ? new Intl.NumberFormat("en-IN").format(r.mcap_cr) : "\u2014"}</td><td className="right">{r.pe ?? "\u2014"}</td><td className="right">{r.roe ?? "\u2014"}</td><td className="right">{r.margin ?? "\u2014"}</td><td className="right"><Change value={r.ret1y} decimals={1} /></td></tr>))}</tbody></table></div>
      </>); }} />
      <Optional title="Events" path={`/api/events/${enc}`} render={(e) => (<>
        <div className="kv"><span>Next results</span><span>{e.next_earnings ? String(e.next_earnings).slice(0, 10) : "No date yet"}</span></div>
        {(e.dividends ?? []).slice(0, 5).map((x: any, i: number) => <div className="kv" key={i}><span>Dividend</span><span>{money(x.amount)} per share, {x.date}</span></div>)}
        {(e.splits ?? []).slice(0, 3).map((x: any, i: number) => <div className="kv" key={"s" + i}><span>Split or bonus</span><span>{x.ratio}:1 on {x.date}</span></div>)}
      </>)} />
      <Optional title="Delivery %" sub="Share of traded quantity actually taken home" path={`/api/delivery/${enc}`} render={(x) => (<><SeriesChart legend={false} height={130} series={[{ name: "Delivery %", color: "#B7791F", data: x.series ?? [] }]} /><p className="note">Rising delivery on up-days reads as real accumulation. Price spikes on low delivery are intraday churn.</p></>)} />
      <Optional title="Market depth" sub="Best five bids and offers, from SmartAPI" path={`/api/depth/${enc}`} render={(x) => (<>
        <div className="sub">Last traded {money(x.ltp)}</div>
        <div className="table-wrap" style={{ margin: "8px -20px 0" }}><table className="table"><thead><tr><th className="right">Qty</th><th className="right">Bid</th><th className="right">Offer</th><th className="right">Qty</th></tr></thead><tbody>{[0, 1, 2, 3, 4].map((i) => (<tr key={i}><td className="right">{x.bids?.[i]?.qty ?? ""}</td><td className="right gain">{x.bids?.[i]?.price ?? ""}</td><td className="right loss">{x.asks?.[i]?.price ?? ""}</td><td className="right">{x.asks?.[i]?.qty ?? ""}</td></tr>))}</tbody></table></div>
        <p className="note">Totals: buy {x.total_buy_qty ?? "\u2014"} against sell {x.total_sell_qty ?? "\u2014"}.</p>
      </>)} />
      <Shareholding symbol={symbol} />
      <Optional title="Options sentiment" sub="F&O stocks only. Context, not a signal" path={`/api/option-sentiment/${enc}`} render={(x) => (<>{Object.entries(x).filter(([, v]) => typeof v !== "object").map(([k, v]) => <div className="kv" key={k}><span>{k.replace(/_/g, " ")}</span><span>{String(v)}</span></div>)}</>)} />
      <Optional title="Documents" sub="Filings the analyst can read" path={`/api/docs/${enc}`} render={(x) => (<>
        {(x.documents ?? []).map((doc: any, i: number) => <div className="kv" key={i}><span>{doc.title ?? doc.filename ?? "Document"}</span><span>{doc.pages ? `${doc.pages} pages` : ""}</span></div>)}
        {(x.documents ?? []).length === 0 && <div className="note">No filings added yet.</div>}
        <Link className="btn" to="/analyst" style={{ marginTop: 10 }}>Open the analyst</Link>
      </>)} />
      <Card title="Read about this stock" sub="Always-current links, not a stale feed"><div style={{ marginTop: 8 }}>{[["Exchange announcements (BSE)", `https://www.bseindia.com/corporates/ann.html`], ["Screener.in page", `https://www.screener.in/company/${base(symbol)}/`], ["News search", `https://news.google.com/search?q=${encodeURIComponent(base(symbol) + " share")}`]].map(([l, u]) => <a key={l} className="kv" href={u} target="_blank" rel="noreferrer" style={{ color: "var(--action)" }}><span style={{ color: "var(--action)", fontWeight: 500 }}>{l}</span><span>Opens in a new tab</span></a>)}</div></Card>
      <StockNews symbol={symbol} />
      <Notes symbol={symbol} />
    </div>
  </>);
}

export function StockView({ raw, compact = false }: { raw: string; compact?: boolean }) {
  const qc = useQueryClient();
  const { symbol, ready } = useResolvedSymbol(raw);
  const prefs = useSettings();
  const [range, setRange] = useState<(typeof RANGES)[number]>(prefs.range);
  const [mode, setMode] = useState<"Line" | "Candles">(prefs.candles ? "Candles" : "Line");
  const [tab, setTab] = useState<"Overview" | "Research">("Overview");
  const [on, setOn] = useState<Set<string>>(new Set(["SMA 50/200", "Volume"]));
  const d = useQuery({ queryKey: ["detail", symbol], queryFn: () => getDetail(symbol), enabled: ready, retry: false, staleTime: DETAIL_STALE_MS });
  const navigate = useNavigate();
  // The server may keep the other exchange's listing (.NS <-> .BO) when this
  // one has no history; follow it. Refetch only this stock's queries; the
  // old blanket invalidateQueries() refetched every page in the app.
  const download = useMutation({
    mutationFn: () => api.post<any>(`/api/download/${encodeURIComponent(symbol)}`),
    meta: { ok: (r: any) => r?.shallow ? `Only ${r.rows} days of history exist for this listing. ${r.note ?? ""}` : `Downloaded ${r?.rows ?? ""} days of history` },
    onSuccess: async (r: any) => {
      qc.invalidateQueries({ predicate: (q) => q.queryKey.some((k) => typeof k === "string" && (k === symbol || k.includes(encodeURIComponent(symbol)))) });
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      if (r?.symbol && r.symbol !== symbol) navigate(`/stocks/${encodeURIComponent(r.symbol)}`, { replace: true });
      else await d.refetch();
    },
  });

  const candles = useMemo(() => (d.data ? d.data.candles.slice(-DAYS[range]) : []), [d.data, range]);
  const from = candles[0]?.time;
  const overlays: Overlays = useMemo(() => {
    if (!d.data || !from) return {};
    const cut = (xs?: any[]) => (xs ?? []).filter((x) => x.time >= from);
    const ind = d.data.indicators ?? {};
    return { sma: on.has("SMA 50/200") ? { fast: cut(d.data.sma_fast), slow: cut(d.data.sma_slow) } : undefined, ema20: on.has("EMA 20") ? cut(ind.ema20) : undefined, bollinger: on.has("Bollinger") ? { upper: cut(ind.bb_upper), lower: cut(ind.bb_lower) } : undefined, volume: on.has("Volume") ? cut(ind.volume) : undefined };
  }, [d.data, from, on]);
  const pane = (key: "rsi" | "macd") => { if (!d.data || !from) return []; const cut = (xs?: any[]) => (xs ?? []).filter((x) => x.time >= from); return key === "rsi" ? [{ name: "RSI 14", color: "#7C4DDB", data: cut(d.data.rsi) }] : [{ name: "MACD", color: "--action", data: cut(d.data.indicators?.macd) }, { name: "Signal", color: "#B7791F", data: cut(d.data.indicators?.macd_signal) }]; };

  if (!ready || d.isLoading) return (<><h1 className="display" style={{ fontSize: 28 }}>{base(raw)}</h1><SkeletonCard lines={3} /><SkeletonCard lines={10} /></>);
  if (d.isError) return (<>
    <h1 className="display" style={{ fontSize: 28 }}>{base(raw)}</h1><ErrorBox error={d.error} />
    <Card title="No price history yet" sub="Download it now, or refresh all data from the ribbon"><button className="btn btn--primary" style={{ marginTop: 12 }} disabled={download.isPending} onClick={() => download.mutate()}>{download.isPending ? "Downloading" : `Download history for ${base(symbol)}`}</button></Card>
  </>);

  const all = d.data.candles; const last = all[all.length - 1], prev = all[all.length - 2];
  const day = last && prev ? (last.close / prev.close - 1) * 100 : null;
  const staleDays = last?.time ? Math.floor((Date.now() - Date.parse(last.time)) / 86_400_000) : null;
  const periodPct = candles.length > 1 ? (candles[candles.length - 1].close / candles[0].close - 1) * 100 : null;
  const f: Record<string, any> = d.data.fundamentals ?? {}; const num = (k: string) => (typeof f[k] === "number" ? (f[k] as number) : null);
  const pos = d.data.position; const stats: Record<string, string> = d.data.stats ?? {};
  const hi = toNum(stats["52w high"]), lo = toNum(stats["52w low"]); const where = hi && lo && last ? Math.max(0, Math.min(100, ((last.close - lo) / (hi - lo)) * 100)) : null;
  const toggle = (k: string) => setOn((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });
  const enc = encodeURIComponent(symbol);

  return (<>
    <div className="pagehead">
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}><h1 style={compact ? { fontSize: 22 } : undefined}>{f.shortName || base(symbol)}</h1><Pill>{symbol}</Pill>{f.sector ? <Pill>{String(f.sector)}</Pill> : null}</div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginTop: 8, flexWrap: "wrap" }}><span className="display" style={{ fontSize: compact ? 30 : 38 }}>{money(last?.close)}</span><span style={{ fontSize: 16 }}><Change value={day} /></span><span className="muted" style={{ fontSize: 13 }}>at the last close, {last?.time}</span></div>
      </div>
      <div className="pagehead__actions"><Link className="btn" to={`/compare?s=${enc}`}>Compare</Link><Link className="btn" to={`/alerts?symbol=${enc}`}>Set alert</Link><Link className="btn" to={`/research/backtest?symbol=${enc}`}>Backtest</Link></div>
    </div>

    {staleDays != null && staleDays > 4 && (
      <div className="callout" style={{ alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", marginBottom: 16 }}>
        <span>Prices here stop at {last?.time}, {staleDays} days ago. Stocks outside your watchlist are not refreshed daily.</span>
        <button className="btn" disabled={download.isPending} onClick={() => download.mutate()}>{download.isPending ? "Updating" : "Update prices"}</button>
      </div>
    )}
    <VerdictCard symbol={symbol} />

    <div className="subnav" role="tablist">{(["Overview", "Research"] as const).map((t) => <a key={t} href="#" role="tab" aria-selected={t === tab} className={t === tab ? "active" : ""} onClick={(e) => { e.preventDefault(); setTab(t); }}>{t}</a>)}</div>

    {tab === "Research" ? <Research symbol={symbol} d={d.data} /> : (<>
      <div className="row">
        <Card className="grow-2">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 10, flexWrap: "wrap" }}>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}><Seg label="Range" options={RANGES} value={range} onChange={setRange} /><Seg label="Chart type" options={["Line", "Candles"] as const} value={mode} onChange={setMode} /></div>
            <span className="secondary">{periodPct != null && <>{periodPct >= 0 ? "Up" : "Down"} <b className={periodPct >= 0 ? "gain" : "loss"}>{Math.abs(periodPct).toFixed(1)}%</b> over this period</>}</span>
          </div>
          <div className="chips" style={{ marginBottom: 10 }}>{INDICATORS.map((k) => <button key={k} type="button" className="chip" aria-pressed={on.has(k)} onClick={() => toggle(k)}>{k}{k === "RSI 14" && <InfoTip k="RSI" />}</button>)}</div>
          <PriceChart candles={candles} overlays={overlays} mode={mode} height={compact ? 320 : 400} />
          {on.has("MACD") && <div style={{ borderTop: "1px solid var(--line)", marginTop: 8, paddingTop: 8 }}><div className="sub">MACD (12, 26, 9)</div><SeriesChart legend={false} height={110} series={pane("macd")} guides={[0]} /></div>}
          {on.has("RSI 14") && <div style={{ borderTop: "1px solid var(--line)", marginTop: 8, paddingTop: 8 }}><div className="sub">RSI 14</div><SeriesChart legend={false} height={110} series={pane("rsi")} guides={[30, 70]} /></div>}
          {where != null && (<div style={{ marginTop: 14 }}><div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5 }} className="muted"><span>52-week low {money(lo)}</span><span>52-week high {money(hi)}</span></div><div className="range"><span style={{ left: `${where}%` }} /></div></div>)}
        </Card>
        <div className="grow" style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {prefs.explain && <Card title="At a glance" sub="Plain-language read of the key numbers">
            <div style={{ marginTop: 8 }}>
              {glance(f).map((g) => (<div key={g.topic} style={{ padding: "12px 0", borderTop: "1px solid var(--line)" }}><div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><b style={{ fontWeight: 500 }}>{g.topic}{g.k && <InfoTip k={g.k} />}</b><Pill kind={g.kind}>{g.word}</Pill></div><div className="secondary" style={{ fontSize: 13, marginTop: 4 }}>{g.line}</div><div className="meter"><span style={{ left: `${g.pos}%`, background: `var(--${g.kind === "guide" ? "guide-text" : g.kind})` }} /></div></div>))}
              {glance(f).length === 0 && <div className="note">No fundamentals stored for this stock yet.</div>}
            </div>
          </Card>}
          {pos && (<Card title="Your position" action={<Link className="btn" style={{ height: 32 }} to="/portfolio/tools">Sell</Link>}><div style={{ marginTop: 8 }}>
            <div className="kv"><span>Held</span><span>{pos.qty} at {money(pos.avg_cost)}</span></div><div className="kv"><span>Invested</span><span>{money(pos.invested, 0)}</span></div>
            <div className="kv"><span>Gain</span><span className={pos.pnl >= 0 ? "gain" : "loss"}>{signed(pos.pnl)} ({pct(pos.pnl_pct, 1)})</span></div>
            {pos.holding_days != null && <div className="kv"><span>Holding for</span><span>{pos.holding_days} days{pos.ltcg_eligible ? ", long term" : ", short term"}</span></div>}
            {pos.dividends ? <div className="kv"><span>Dividends</span><span>{money(pos.dividends, 0)}</span></div> : null}
            <div className="kv"><span>Stock against index since you bought</span><span><Change value={pos.stock_ret_since} decimals={1} /> against <Change value={pos.index_ret_since} decimals={1} /></span></div>
          </div></Card>)}
        </div>
      </div>
      <div className="row">
        <Card className="grow" title="Fundamentals">
          <div className="grid grid-4" style={{ marginTop: 14 }}>
            <Stat label="Market cap" value={compactMoney(num("marketCap"))} /><Stat label="P/E ratio" value={num("trailingPE")?.toFixed(1) ?? "\u2014"} /><Stat label="P/B ratio" value={num("priceToBook")?.toFixed(1) ?? "\u2014"} /><Stat label="ROE" value={num("returnOnEquity") != null ? (num("returnOnEquity")! * 100).toFixed(1) + "%" : "\u2014"} />
            <Stat label="Debt to equity" value={num("debtToEquity") != null ? (num("debtToEquity")! / 100).toFixed(2) : "\u2014"} /><Stat label="Net margin" value={num("profitMargins") != null ? (num("profitMargins")! * 100).toFixed(1) + "%" : "\u2014"} /><Stat label="Dividend yield" value={num("dividendYield") != null ? num("dividendYield")!.toFixed(2) + "%" : "\u2014"} /><Stat label="Beta" value={num("beta")?.toFixed(2) ?? "\u2014"} />
          </div>
          {d.data.fundamentals_updated && <p className="note">Fundamentals as of {String(d.data.fundamentals_updated).slice(0, 10)}. Cross-check on the company's filings before any decision.</p>}
        </Card>
        <Card className="grow" title="Price and trend"><div style={{ marginTop: 8 }}>{Object.entries(stats).map(([k, v]) => <div className="kv" key={k}><span><Term>{k}</Term></span><span>{v}</span></div>)}</div></Card>
      </div>
    </>)}
  </>);
}
