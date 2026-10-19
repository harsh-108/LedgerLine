import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { Card, ErrorBox, PageHead, Seg } from "../components/ui";
import { RecordsTable } from "../components/RecordsTable";
import { Job } from "../components/Section";
import { InfoTip } from "../components/InfoTip";
import { Icon } from "../components/Icon";
import { useMe } from "../lib/useMe";

/* eslint-disable @typescript-eslint/no-explicit-any */
const FIELDS = "pe pb roe margin divyield de eps beta mcap close rsi ret1m ret6m ret1y trend sector".split(" ");
const NAMES: Record<string, string> = { watchlist: "My watchlist", nifty50: "NIFTY 50", nifty100: "NIFTY 100", nifty500: "NIFTY 500" };

// Filters view: each one becomes a condition in the same query language.
interface FilterDef { key: string; label: string; hint: string; info?: string; min: number; max: number; step: number; unit?: string }
const DEFS: FilterDef[] = [
  { key: "mcap", label: "Market cap", hint: "In crore. 20,000 and up is roughly large cap", min: 0, max: 500000, step: 1000, unit: "Cr" },
  { key: "pe", label: "P/E ratio", info: "P/E", hint: "How many years of profit the price equals. Lower is cheaper", min: 0, max: 100, step: 1 },
  { key: "pb", label: "P/B ratio", info: "P/B", hint: "Price against the company's net assets", min: 0, max: 30, step: 0.5 },
  { key: "roe", label: "ROE", info: "ROE %", hint: "How well the company turns your money into profit", min: -20, max: 60, step: 1, unit: "%" },
  { key: "de", label: "Debt to equity", info: "D/E", hint: "In percent. 50 means it owes 0.5 for every 1 of its own. Lower means less borrowing", min: 0, max: 300, step: 5, unit: "%" },
  { key: "margin", label: "Net margin", hint: "Profit kept from each 100 of sales", min: -20, max: 60, step: 1, unit: "%" },
  { key: "divyield", label: "Dividend yield", info: "Div yield %", hint: "Yearly dividend as a share of the price", min: 0, max: 12, step: 0.25, unit: "%" },
  { key: "rsi", label: "RSI", info: "RSI", hint: "Under 30 is called oversold, over 70 overbought", min: 0, max: 100, step: 1 },
  { key: "ret6m", label: "6 month return", hint: "Price change over six months", min: -60, max: 150, step: 5, unit: "%" },
  { key: "ret1y", label: "1 year return", hint: "Price change over a year", min: -60, max: 200, step: 5, unit: "%" },
  { key: "beta", label: "Beta", info: "Beta", hint: "How much it swings against the market. 1 moves with it", min: 0, max: 3, step: 0.1 },
];
type Range = { min: string; max: string };
const READY: { label: string; ranges: Record<string, Range>; trend?: string; sort: string }[] = [
  { label: "Low debt, high ROE", ranges: { roe: { min: "15", max: "" }, de: { min: "", max: "50" } }, sort: "roe desc" },
  { label: "Cheap and in an uptrend", ranges: { pe: { min: "", max: "20" } }, trend: "up", sort: "ret6m desc" },
  { label: "Dividend payers", ranges: { divyield: { min: "2", max: "" } }, sort: "divyield desc" },
  { label: "Oversold quality", ranges: { rsi: { min: "", max: "35" }, roe: { min: "12", max: "" } }, sort: "rsi asc" },
];

function build(ranges: Record<string, Range>, trend: string, sort: string) {
  const parts: string[] = [];
  for (const [k, r] of Object.entries(ranges)) { if (r.min !== "") parts.push(`${k} > ${r.min}`); if (r.max !== "") parts.push(`${k} < ${r.max}`); }
  if (trend) parts.push(`trend = ${trend}`);
  if (!parts.length) return "";
  return parts.join(" and ") + (sort ? ` sort by ${sort}` : "");
}

export default function Screener() {
  const { isAdmin } = useMe();                // preparing a universe is admin-only
  const [view, setView] = useState<"Filters" | "Query">((localStorage.getItem("screenerView") as any) === "Query" ? "Query" : "Filters");
  const [universe, setUniverse] = useState("watchlist");
  const unis = useQuery({ queryKey: ["universes"], queryFn: () => api.get<{ universes: any[] }>("/api/universes") });
  const run = useMutation({ mutationFn: (q: string) => api.get<any>(`/api/query?q=${encodeURIComponent(q)}&universe=${universe}`), meta: { quiet: true } });
  const u = unis.data?.universes.find((x) => x.name === universe);

  // ---- filters view state
  const [ranges, setRanges] = useState<Record<string, Range>>({ roe: { min: "15", max: "" }, de: { min: "", max: "50" } });
  const [trend, setTrend] = useState("");
  const [sort, setSort] = useState("roe desc");
  const [params] = useSearchParams();
  useEffect(() => { const r = READY.find((x) => x.label === params.get("screen")); if (r) { setView("Filters"); setRanges(r.ranges); setTrend(r.trend ?? ""); setSort(r.sort); } }, [params]);
  const built = useMemo(() => build(ranges, trend, sort), [ranges, trend, sort]);
  // live count: run shortly after the last change
  useEffect(() => { if (view !== "Filters" || !built) return; const t = setTimeout(() => run.mutate(built), 450); return () => clearTimeout(t); }, [built, universe, view]); // eslint-disable-line react-hooks/exhaustive-deps
  // Query view: switching universe re-runs the last query on the new one.
  // Without this the old result ("7 matches out of 63", the watchlist) stayed
  // on screen under the newly selected NIFTY 500 chip.
  useEffect(() => { if (view === "Query" && typeof run.variables === "string") run.mutate(run.variables); }, [universe]); // eslint-disable-line react-hooks/exhaustive-deps
  const setR = (k: string, side: "min" | "max", v: string) => setRanges((r) => ({ ...r, [k]: { ...r[k], [side]: v } }));
  const drop = (k: string) => setRanges((r) => { const n = { ...r }; delete n[k]; return n; });
  const unused = DEFS.filter((d) => !(d.key in ranges));

  // ---- query view state
  const [english, setEnglish] = useState("");
  const [query, setQuery] = useState("roe > 15 and de < 50 sort by roe desc");
  // errors show under the English box (meta.quiet: no toast as well), so a
  // multi-paragraph refusal from the injection gate stays readable
  const translate = useMutation({ mutationFn: () => api.get<{ generated_query: string }>(`/api/nlq?text=${encodeURIComponent(english)}`), meta: { quiet: true }, onSuccess: (d) => { setQuery(d.generated_query); run.mutate(d.generated_query); } });

  const rows: any[] = run.data?.rows ?? [];
  const near: any[] = run.data?.diagnostics?.near_misses ?? [];
  const pick = (v: "Filters" | "Query") => { setView(v); localStorage.setItem("screenerView", v); if (v === "Query" && built) setQuery(built); };
  const chips = [...Object.entries(ranges).flatMap(([k, r]) => { const d = DEFS.find((x) => x.key === k)!; const out: [string, () => void][] = []; if (r.min !== "") out.push([`${d.label} over ${r.min}${d.unit === "%" ? "%" : ""}`, () => setR(k, "min", "")]); if (r.max !== "") out.push([`${d.label} under ${r.max}${d.unit === "%" ? "%" : ""}`, () => setR(k, "max", "")]); return out; }), ...(trend ? [[`Trend is ${trend}`, () => setTrend("")] as [string, () => void]] : [])];

  const results = (<>
    {run.isError && <ErrorBox error={run.error} />}
    {run.data && rows.length === 0 && (<Card title={`Nothing matches all ${chips.length || ""} conditions`} sub="Closest misses, so you can see which condition to loosen"><div style={{ margin: "10px -20px -20px" }}><RecordsTable rows={near} empty="No near misses either. Try fewer conditions." /></div></Card>)}
    {rows.length > 0 && <Card flush><RecordsTable rows={rows} /></Card>}
  </>);

  return (
    <>
      <PageHead title="Screener"
        sub={run.data ? <><b style={{ color: rows.length ? "var(--ink)" : "var(--loss)" }}>{rows.length} match{rows.length === 1 ? "" : "es"}</b> out of {run.data.diagnostics?.universe_size ?? "?"}. The count updates as you change filters.</> : "Filter your watchlist or a whole index"}
        actions={<Seg label="View" options={["Filters", "Query"] as const} value={view} onChange={pick} />} />
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span className="secondary" style={{ fontWeight: 500, marginRight: 4 }}>Universe</span>
        {(unis.data?.universes ?? [{ name: "watchlist" }]).map((x) => (<button key={x.name} className="chip" style={{ height: 36, borderRadius: 999 }} aria-pressed={x.name === universe} onClick={() => setUniverse(x.name)}>{NAMES[x.name] ?? x.name}</button>))}
        {u && (u.error ? <span className="muted" style={{ marginLeft: 8 }}>{u.error}</span> : <span className="muted" style={{ marginLeft: 8 }}>{u.with_prices} of {u.total} have data</span>)}
        {isAdmin && u && u.missing > 0 && universe !== "watchlist" && <Job label="Download missing data" start={`/api/universe/${universe}/prepare`} status="/api/universe/status" />}
      </div>

      {view === "Filters" ? (
        <div className="row" style={{ alignItems: "flex-start" }}>
          <Card className="filters">
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>{READY.map((r) => <button key={r.label} type="button" className="chip" onClick={() => { setRanges(r.ranges); setTrend(r.trend ?? ""); setSort(r.sort); }}>{r.label}</button>)}</div>
            {Object.keys(ranges).map((k) => { const d = DEFS.find((x) => x.key === k)!; const r = ranges[k]; const lo = r.min === "" ? d.min : Number(r.min), hi = r.max === "" ? d.max : Number(r.max); const pct = (v: number) => Math.max(0, Math.min(100, ((v - d.min) / (d.max - d.min)) * 100)); return (
              <div key={k} className="filter">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><b style={{ fontWeight: 500 }}>{d.label}{d.unit ? <span className="muted"> ({d.unit})</span> : null}{d.info && <InfoTip k={d.info} />}</b><button type="button" className="btn btn--quiet" style={{ height: 24, padding: 0 }} aria-label={`Remove ${d.label} filter`} onClick={() => drop(k)}><Icon name="x" size={14} /></button></div>
                <div className="track"><span style={{ left: `${pct(lo)}%`, width: `${Math.max(0, pct(hi) - pct(lo))}%` }} /></div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input aria-label={`${d.label} minimum`} type="number" step={d.step} placeholder="Any" value={r.min} onChange={(e) => setR(k, "min", e.target.value)} />
                  <span className="muted" style={{ fontSize: 13 }}>to</span>
                  <input aria-label={`${d.label} maximum`} type="number" step={d.step} placeholder="Any" value={r.max} onChange={(e) => setR(k, "max", e.target.value)} />
                </div>
                <div className="note" style={{ marginTop: 6 }}>{d.hint}</div>
              </div>); })}
            <div className="filter">
              <b style={{ fontWeight: 500 }}>Trend</b>
              <div style={{ marginTop: 8 }}><Seg label="Trend" options={["Any", "up", "down"] as const} value={(trend || "Any") as any} onChange={(v) => setTrend(v === "Any" ? "" : v)} /></div>
              <div className="note" style={{ marginTop: 6 }}>Up means the 50-day average is above the 200-day</div>
            </div>
            {unused.length > 0 && (<div className="f" style={{ marginTop: 12 }}><label htmlFor="addf" className="sr-only">Add a filter</label><select id="addf" value="" onChange={(e) => e.target.value && setRanges((r) => ({ ...r, [e.target.value]: { min: "", max: "" } }))} style={{ borderStyle: "dashed", color: "var(--action)", fontWeight: 500 }}><option value="">+ Add a filter</option>{unused.map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}</select></div>)}
            <div className="f" style={{ marginTop: 12 }}><label htmlFor="srt">Sort by</label><select id="srt" value={sort} onChange={(e) => setSort(e.target.value)}>{DEFS.flatMap((d) => [[`${d.key} desc`, `${d.label}, high to low`], [`${d.key} asc`, `${d.label}, low to high`]]).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
          </Card>
          <div className="grow" style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
            <div className="chips" style={{ alignItems: "center" }}>
              {chips.map(([t, off]) => (<span key={t} className="chip" aria-pressed="true" style={{ borderRadius: 999, height: 32 }}>{t}<button type="button" aria-label={`Remove ${t}`} onClick={off} style={{ border: "none", background: "transparent", color: "inherit", padding: 0, display: "flex" }}><Icon name="x" size={13} /></button></span>))}
              {chips.length > 0 && <button type="button" className="btn btn--quiet" style={{ height: 32 }} onClick={() => { setRanges({}); setTrend(""); }}>Clear all</button>}
              {run.isPending && <span className="muted" style={{ fontSize: 13 }}>Counting</span>}
            </div>
            {!built && <Card title="Add a filter to begin" sub="Or pick a ready-made screen on the left"><span /></Card>}
            {results}
            {built && <p className="note">As a query: <code>{built}</code>. Switch to Query view to edit it by hand.</p>}
          </div>
        </div>
      ) : (<>
        <Card>
          <form onSubmit={(e: FormEvent) => { e.preventDefault(); if (english.trim()) translate.mutate(); }} className="f"><label htmlFor="nl" style={{ fontSize: 15, fontWeight: 600, color: "var(--ink)" }}>Ask in plain English</label>
            <div style={{ display: "flex", gap: 10 }}><input id="nl" value={english} onChange={(e) => setEnglish(e.target.value)} placeholder="cheap IT stocks in an uptrend" style={{ height: 48 }} /><button className="btn btn--primary" style={{ height: 48, marginTop: 6 }} disabled={translate.isPending}>{translate.isPending ? "Translating" : "Translate and run"}</button></div>
            {translate.isError && <div className="error" role="alert" style={{ marginTop: 10, whiteSpace: "pre-wrap" }}>{(translate.error as Error).message}</div>}</form>
          <form onSubmit={(e: FormEvent) => { e.preventDefault(); run.mutate(query); }} className="f" style={{ marginTop: 16 }}><label htmlFor="ql" style={{ fontSize: 15, fontWeight: 600, color: "var(--ink)" }}>Query</label>
            <div style={{ display: "flex", gap: 10 }}><input id="ql" value={query} onChange={(e) => setQuery(e.target.value)} style={{ height: 48, fontFamily: "ui-monospace, Menlo, monospace" }} /><button className="btn" style={{ height: 48, marginTop: 6 }} disabled={run.isPending}>{run.isPending ? "Running" : "Run"}</button></div></form>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 14, alignItems: "center" }}><span className="muted" style={{ fontSize: 13 }}>Fields</span>{FIELDS.map((f) => <button key={f} type="button" className="pill" style={{ border: "none", fontFamily: "ui-monospace, Menlo, monospace", cursor: "pointer" }} onClick={() => setQuery((q) => `${q} ${f}`.trim())}>{f}</button>)}</div>
          <p className="note">Join conditions with and, or. Add sort by and top N. Plain English needs an AI key in .env.{run.data?.explanation ? ` Read as: ${run.data.explanation}.` : ""}</p>
        </Card>
        {results}
      </>)}
    </>
  );
}
