import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { base, exchange, money, pct } from "../lib/format";
import { CALL_KIND, signalLabel } from "../lib/labels";
import { RESEARCH } from "../lib/nav";
import { setSettings, useSettings } from "../lib/settings";
import { useWatchSymbols } from "../lib/symbols";
import { Card, Change, ErrorBox, PageHead, Pill, Seg, SkeletonCard, Stat } from "../components/ui";
import { RecordsTable } from "../components/RecordsTable";
import { SeriesChart } from "../components/SeriesChart";
import { Job, SubNav, SymbolSelect } from "../components/Section";
import { StockPicker } from "../components/StockPicker";
import { InfoTip, Term } from "../components/InfoTip";
import { DaysSelect, TrackOnScorecard } from "../components/TrackOnScorecard";

/* eslint-disable @typescript-eslint/no-explicit-any */
const NOTE = "Buy, hold and sell calls come from the app's own checks on stored, possibly delayed data. Not investment advice.";

function ZBar({ v }: { v: number | null }) {
  if (v == null) return <span className="muted">&mdash;</span>;
  const w = Math.min(48, (Math.abs(v) / 2.5) * 48);
  return (<div style={{ display: "flex", alignItems: "center", gap: 8 }}><div style={{ position: "relative", flex: 1, height: 10, minWidth: 60 }}><span style={{ position: "absolute", left: "50%", top: -2, bottom: -2, width: 1, background: "var(--line)" }} /><span style={{ position: "absolute", top: 0, height: 10, borderRadius: 3, width: `${w}%`, background: v >= 0 ? "var(--gain)" : "var(--loss)", ...(v >= 0 ? { left: "50%" } : { right: "50%" }) }} /></div><span style={{ width: 38, textAlign: "right", fontSize: 13 }}>{v >= 0 ? "+" : ""}{v.toFixed(1)}</span></div>);
}

export function AILab() {
  const symbols = useWatchSymbols();
  const [sym, setSym] = useState("");
  const ranks = useQuery({ queryKey: ["rankings"], staleTime: 5 * 60_000, queryFn: () => api.get<any>("/api/rankings") });
  const predict = useMutation({ mutationFn: (s: string) => api.get<any>(`/api/predict/${encodeURIComponent(s)}`) });
  const rows: any[] = ranks.data?.rows ?? [];
  const w = ranks.data?.weights ?? {};
  return (
    <>
      <PageHead title="AI Lab" sub="Quantitative views of your watchlist" /><SubNav items={RESEARCH} />
      <div className="row">
        <Card flush className="grow-2" title="Factor rankings" sub={`Momentum ${Math.round((w.momentum ?? 0.3) * 100)}%, value ${Math.round((w.value ?? 0.25) * 100)}%, quality ${Math.round((w.quality ?? 0.25) * 100)}%, trend ${Math.round((w.trend ?? 0.2) * 100)}%. Scored against your watchlist.`}>
          {ranks.isLoading && <div style={{ padding: 20 }}><SkeletonCard lines={6} /></div>}
          {ranks.isError && <div style={{ padding: 20 }}><ErrorBox error={ranks.error} /></div>}
          <div className="table-wrap"><table className="table">
            <thead><tr><th>#</th><th>Stock</th><th className="right"><Term>Score</Term></th><th><Term>Momentum z</Term></th><th><Term>Value z</Term></th><th><Term>Quality z</Term></th><th><Term>Trend z</Term></th></tr></thead>
            <tbody>{rows.filter((r) => r.Score != null).map((r, i) => (<tr key={r.Symbol}><td className="muted">{i + 1}</td><td className="name"><Link to={`/stocks/${encodeURIComponent(r.Symbol)}`}>{base(r.Symbol)}</Link></td><td className="right"><b>{r.Score >= 0 ? "+" : ""}{Number(r.Score).toFixed(2)}</b></td><td><ZBar v={r["Momentum z"]} /></td><td><ZBar v={r["Value z"]} /></td><td><ZBar v={r["Quality z"]} /></td><td><ZBar v={r["Trend z"]} /></td></tr>))}</tbody>
          </table></div>
          <p className="note" style={{ padding: "0 20px 16px" }}>A ranking, not a prediction.</p>
        </Card>
        <Card className="grow" title="Next-day model" action={<Pill kind="guide">Educational</Pill>}>
          <div style={{ marginTop: 12 }}><SymbolSelect id="nds" value={sym} onChange={setSym} symbols={symbols} /></div>
          <button className="btn" style={{ marginTop: 12 }} disabled={!sym || predict.isPending} onClick={() => predict.mutate(sym)}>{predict.isPending ? "Training" : "Train and evaluate"}</button>
          {predict.isError && <div style={{ marginTop: 10 }}><ErrorBox error={predict.error} /></div>}
          {predict.data && (<>
            <div style={{ marginTop: 14, textAlign: "center", padding: 20, borderRadius: 12, background: "var(--ground)" }}><div className="muted" style={{ fontSize: 13 }}>Chance of closing up tomorrow<InfoTip k="P(up tomorrow)" /></div><div className="display" style={{ fontSize: 44 }}>{Math.round(predict.data.prob_up * 100)}%</div></div>
            <div style={{ marginTop: 10 }}>
              <div className="kv"><span><Term>Test accuracy</Term></span><span>{(predict.data.test_accuracy * 100).toFixed(1)}%</span></div>
              <div className="kv"><span><Term>Naive baseline</Term></span><span>{(predict.data.baseline_accuracy * 100).toFixed(1)}%</span></div>
              <div className="kv"><span><Term>Edge</Term></span><span className={predict.data.edge >= 0 ? "gain" : "loss"}>{(predict.data.edge * 100).toFixed(1)} pts</span></div>
              <div className="kv"><span>Tested on</span><span>{predict.data.test_period}</span></div>
            </div>
            <div className="callout" style={{ marginTop: 10 }}>{predict.data.verdict_text}</div>
            <TrackOnScorecard symbol={predict.data.symbol ?? predict.variables ?? sym} source="ai_lab" runId={predict.data} what="this prediction is graded after the next trading day, and the app's daily verdict on it is written down too" after="This prediction is graded after the next trading day." />
          </>)}
          <p className="note">Trained on the past and tested on the most recent 30% it never saw. Honest expectation: 50 to 55% accuracy. Every prediction is written down; it shows on the Scorecard once the stock is tracked there.</p>
        </Card>
      </div>
    </>
  );
}

export function Backtest() {
  const symbols = useWatchSymbols();
  const [params] = useSearchParams();
  const [sym, setSym] = useState(params.get("symbol") ?? "");
  const [strategy, setStrategy] = useState("golden_cross");
  const [cost, setCost] = useState("0.2");
  const strategies = useQuery({ queryKey: ["strategies"], queryFn: () => api.get<{ strategies: any[] }>("/api/strategies") });
  type RunArgs = { sym: string; strategy: string; cost: string };
  const run = useMutation({ mutationFn: (a: RunArgs) => api.get<any>(`/api/backtest/${encodeURIComponent(a.sym)}?strategy=${a.strategy}&cost=${encodeURIComponent(a.cost)}`) });
  const all = useMutation({ mutationFn: (a: RunArgs) => api.get<any>(`/api/backtest-all/${encodeURIComponent(a.sym)}?cost=${encodeURIComponent(a.cost)}`) });
  // Default to the first watchlist stock ONCE. The picker reports "" while
  // the user types, and re-defaulting on every "" overwrote their typing.
  const defaulted = useRef(!!sym);
  useEffect(() => { if (!defaulted.current && symbols[0]) { defaulted.current = true; setSym(symbols[0]); } }, [symbols]);
  const r = run.data;
  const series = useMemo(() => (r ? [{ name: r.strategy_label, color: "--action", data: r.curves.map((c: any) => ({ time: c.time, value: c.strategy })) }, { name: "Buy and hold", color: "--slate", data: r.curves.map((c: any) => ({ time: c.time, value: c.hold })) }] : []), [r]);
  const args = (): RunArgs => ({ sym, strategy, cost: cost.trim() || "0" });
  const onRun = (e: FormEvent) => { e.preventDefault(); if (sym) run.mutate(args()); };
  const holding = !!r?.now?.invested;
  return (
    <>
      <PageHead title="Backtest" sub="See how a simple rule would have done on a stock, with trading costs included" /><SubNav items={RESEARCH} />
      <Card><form className="form-row" onSubmit={onRun}>
        <div style={{ flex: "1.3 1 220px", minWidth: 0 }}><SymbolSelect id="bts" value={sym} onChange={setSym} symbols={symbols} /></div>
        <div className="f" style={{ flex: "1.3 1 220px" }}><label htmlFor="btst">Strategy<InfoTip k={strategy} /></label><select id="btst" value={strategy} onChange={(e) => setStrategy(e.target.value)}>{strategies.data?.strategies.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</select></div>
        <div className="f" style={{ flex: "0 1 150px" }}><label htmlFor="btc">Cost per side, %<InfoTip k="Cost per side" /></label><input id="btc" type="number" step="0.01" min="0" max="5" value={cost} onChange={(e) => setCost(e.target.value)} /></div>
        <button className="btn btn--primary" disabled={!sym || run.isPending}>{run.isPending ? "Running" : "Run"}</button>
        <button type="button" className="btn" disabled={!sym || all.isPending} onClick={() => all.mutate(args())}>{all.isPending ? "Comparing" : "Compare all"}</button>
      </form>{strategies.data && <p className="note" style={{ marginBottom: 0 }}>{strategies.data.strategies.find((s) => s.key === strategy)?.desc} Costs of {Number(cost) || 0}% are charged on every buy and every sell.</p>}</Card>
      {run.isError && <ErrorBox error={run.error} />}
      {r && (<>
        <div className="grid grid-5">
          <div className="card"><Stat label="Strategy CAGR" value={pct(r.strategy.cagr, 1)} detail={<span className="muted">buy and hold {pct(r.buy_hold.cagr, 1)}</span>} /></div>
          <div className="card"><Stat label="Max fall" value={<span className="loss">{pct(r.strategy.max_dd, 1)}</span>} detail={<span className="muted">buy and hold {pct(r.buy_hold.max_dd, 1)}</span>} /></div>
          <div className="card"><Stat label="Win rate" value={r.win_rate == null ? "\u2014" : `${Math.round(r.win_rate)}%`} detail={<span className="muted">of {r.n_trades} completed trade{r.n_trades === 1 ? "" : "s"}</span>} /></div>
          <div className="card"><Stat label="Tested over" value={`${r.years} years`} detail={<span className="muted">of daily prices</span>} /></div>
          <div className="card"><Stat label="What the rule says now" value={<span className={holding ? "gain" : "secondary"}>{holding ? "Holding the stock" : "Out of the stock"}</span>} detail={<span className="muted">{r.now?.since ? <>since {r.now.since}, when {r.now.why}</> : holding ? "since the start of the test" : "it has not bought yet"}</span>} /></div>
        </div>
        <Card title="Strategy against buy and hold" sub={r.summary}>
          <div style={{ marginTop: 12 }}><SeriesChart series={series} height={280} /></div>
          <TrackOnScorecard symbol={r.symbol} source="backtest" runId={r} rule={{ strategy: r.strategy_key, cost: Number(run.variables?.cost ?? cost) || 0 }}
            what={`the rule's call today (${holding ? "holding" : "out of the stock"}) is graded once the period ends`} after={`Its call today (${holding ? "holding" : "out of the stock"}) is graded when the period ends.`} />
        </Card>
        <Card flush title="Trades"><RecordsTable rows={r.trades} symbolKey="" empty="No completed trades." /></Card>
      </>)}
      {all.isError && <ErrorBox error={all.error} />}
      {all.data && <Card flush title="All strategies compared" sub={`Same stock, same cost of ${Number(all.variables?.cost) || 0}% per side.`}><RecordsTable symbolKey="" rows={all.data.rows.map((x: any) => ({ Strategy: x.label, "CAGR %": x.cagr, "Max fall %": x.max_dd, Trades: x.trades, "Win rate": x.win_rate, "Beat buy and hold": x.beat_hold, "Rule says now": x.now?.invested ? "Holding" : "Out" }))} /></Card>}
      <p className="note">Past results do not predict future results. A rule that lowers the worst fall can still earn less than holding. {NOTE}</p>
    </>
  );
}

const SOURCE: Record<string, string> = { manual: "Added by you", watchlist: "Your watchlist", portfolio: "Your portfolio", backtest: "Backtest", ai_lab: "AI Lab", analyst: "Analyst" };
const CALL_WORD: Record<string, string> = { strong: "Buy", mixed: "Hold", weak: "Sell", up: "Up", down: "Down", in: "Buy (in the stock)", out: "Sell (out of the stock)" };
type Kind = "All" | "Verdict card" | "Checklist tier" | "Next-day model" | "Backtest rule";
const KIND_MATCH: Record<Exclude<Kind, "All">, (k: string) => boolean> = { "Verdict card": (k) => k === "verdict", "Checklist tier": (k) => k === "checklist", "Next-day model": (k) => k === "ml_nextday", "Backtest rule": (k) => k.startsWith("rule_") };

export function Scorecard() {
  const qc = useQueryClient();
  const st = useSettings();
  const [kind, setKind] = useState<Kind>("All");
  const [status, setStatus] = useState<"All" | "Graded" | "Waiting">("All");
  const [filter, setFilter] = useState("");
  const [track, setTrack] = useState("");
  const [days, setDays] = useState(st.trackDays);
  const sc = useQuery({ queryKey: ["scorecard"], queryFn: () => api.get<any>("/api/scorecard") });
  const tracked = useQuery({ queryKey: ["tracked"], queryFn: () => api.get<{ tracked: any[] }>("/api/scorecard/track") });
  const strategies = useQuery({ queryKey: ["strategies"], queryFn: () => api.get<{ strategies: any[] }>("/api/strategies") });
  const kindLabel = (k: string) => (k.startsWith("rule_") ? `Backtest: ${strategies.data?.strategies.find((x) => x.key === k.slice(5))?.label ?? k.slice(5).replace(/_/g, " ")}` : CALL_KIND[k] ?? k);
  const inval = () => { qc.invalidateQueries({ queryKey: ["tracked"] }); qc.invalidateQueries({ queryKey: ["scorecard"] }); };
  const added = (r: any) => { const a = r?.added ?? 0, e = r?.extended ?? 0; return a || e ? `${a ? `${a} stock${a === 1 ? "" : "s"} added` : ""}${a && e ? ", " : ""}${e ? `${e} extended` : ""}` : "Already being tracked"; };
  const add = useMutation({ mutationFn: (b: { symbols: string[]; source: string }) => api.post<any>("/api/scorecard/track", { ...b, days: days || null }), meta: { ok: added }, onSuccess: () => { setTrack(""); inval(); } });
  const rm = useMutation({ mutationFn: (s: string) => api.del(`/api/scorecard/track/${encodeURIComponent(s)}`), meta: { ok: "Stopped tracking. Calls already recorded are kept." }, onSuccess: inval });
  const setPeriod = useMutation({ mutationFn: (x: { symbol: string; days: number }) => api.patch<any>(`/api/scorecard/track/${encodeURIComponent(x.symbol)}`, { days: x.days || null }), meta: { ok: "Tracking period updated" }, onSuccess: inval });
  const rows: any[] = (sc.data?.rows ?? []).filter((r: any) => (kind === "All" || KIND_MATCH[kind](r.kind)) && (status === "All" || (status === "Graded" ? r.outcome != null : r.outcome == null)) && (!filter || r.symbol.toLowerCase().includes(filter.toLowerCase())));
  const list = tracked.data?.tracked ?? [];
  const activeN = list.filter((t) => t.active).length;
  return (
    <>
      <PageHead title="Scorecard" sub="Your own record of the app's calls. Every verdict, checklist tier, next-day prediction and backtest rule on the stocks you look at and track is written down with that day's price and checked later. Other accounts have their own Scorecard." /><SubNav items={RESEARCH} />
      {sc.isError && <ErrorBox error={sc.error} />}
      {(sc.data?.summary ?? []).some((s: any) => s.total > 0) && (
        <div className="stat-grid">{(sc.data?.summary ?? []).filter((s: any) => s.total > 0).map((s: any) => (<div className="card" key={`${s.kind}-${s.horizon_days}`}><Stat big label={`${kindLabel(s.kind)}, ${s.horizon_days} day${s.horizon_days === 1 ? "" : "s"}`} value={s.accuracy != null ? `${s.accuracy}% right` : "\u2014"} detail={<span className="muted">{s.scored} graded, {s.pending} waiting{s.beat_index_pct != null ? `. Beat the index ${s.beat_index_pct}% of the time` : ""}</span>} /></div>))}</div>
      )}

      <Card title="Stocks being tracked" sub={<>Every day after the data refresh, each tracked stock gets the app's verdict and checklist tier written down, for as long as its tracking period runs.<InfoTip k="Tracking period" /></>}>
        <div className="track-prefs">
          <div><div className="track-prefs__k">When you run a backtest, the next-day model, or ask the analyst about a stock</div>
            <div className="seg" role="group" aria-label="Adding to the Scorecard" style={{ marginTop: 6 }}>
              <button type="button" aria-pressed={st.autoTrack} onClick={() => setSettings({ autoTrack: true })}>Add it automatically</button>
              <button type="button" aria-pressed={!st.autoTrack} onClick={() => setSettings({ autoTrack: false })}>Show me a button to add it</button>
            </div></div>
          <div><label className="track-prefs__k" htmlFor="tdef">Default tracking period</label><div style={{ marginTop: 6 }}><DaysSelect id="tdef" small value={st.trackDays} onChange={(d) => { setSettings({ trackDays: d }); setDays(d); }} /></div></div>
        </div>
        <form className="toolbar" style={{ marginTop: 16 }} onSubmit={(e) => { e.preventDefault(); if (track.trim()) add.mutate({ symbols: [track.trim().toUpperCase()], source: "manual" }); }}>
          <div style={{ flex: "1 1 260px", maxWidth: 360 }}><StockPicker id="trk" label="Track a stock" hideLabel value={track} onChange={setTrack} disabled={add.isPending} /></div>
          <label className="trackbar__days"><span>for</span><DaysSelect id="tdays" small value={days} onChange={setDays} /></label>
          <button className="btn btn--primary" disabled={!track.trim() || add.isPending} style={{ height: 36 }}>Track</button>
          <span className="toolbar__end">
            <button type="button" className="btn" style={{ height: 36 }} disabled={add.isPending} onClick={() => add.mutate({ symbols: [], source: "watchlist" })}>Add my watchlist</button>
            <button type="button" className="btn" style={{ height: 36 }} disabled={add.isPending} onClick={() => add.mutate({ symbols: [], source: "portfolio" })}>Add my portfolio</button>
          </span>
        </form>
        {add.isError && <div style={{ marginTop: 10 }}><ErrorBox error={add.error} /></div>}
        {list.length === 0 ? <p className="note" style={{ marginTop: 14 }}>Nothing is tracked yet. Add a stock above, or run a backtest or the next-day model and add it from there. Until something is tracked, every call recorded for you is shown below.</p> : (
          <div className="table-wrap" style={{ marginTop: 14, marginInline: -20 }}><table className="table">
            <thead><tr><th>Stock</th><th>Added from</th><th>Started</th><th><Term>Track for</Term></th><th>Status</th><th className="right">Calls recorded</th><th className="right"><span className="sr-only">Remove</span></th></tr></thead>
            <tbody>{list.map((t) => (<tr key={t.symbol}>
              <td className="name"><Link to={`/stocks/${encodeURIComponent(t.symbol)}`}>{base(t.symbol)}</Link> {exchange(t.symbol) && <span className="pill" style={{ height: 20, fontSize: 11 }}>{exchange(t.symbol)}</span>}</td>
              <td className="secondary">{SOURCE[t.source] ?? t.source ?? "\u2014"}</td>
              <td className="secondary">{String(t.added_at).slice(0, 10)}</td>
              <td><DaysSelect id={`tp-${t.symbol}`} label={`Tracking period for ${base(t.symbol)}`} small value={t.days ?? 0} onChange={(d) => setPeriod.mutate({ symbol: t.symbol, days: d })} /></td>
              <td>{!t.until ? <Pill kind="action">Ongoing</Pill> : t.active ? <span><Pill kind="gain">Active</Pill> <span className="muted" style={{ fontSize: 12.5 }}>{t.days_left} day{t.days_left === 1 ? "" : "s"} left, until {t.until}</span></span> : <span><Pill>Ended</Pill> <span className="muted" style={{ fontSize: 12.5 }}>on {t.until}</span></span>}</td>
              <td className="right">{t.calls}</td>
              <td className="right"><button className="btn btn--quiet" style={{ height: 30 }} aria-label={`Stop tracking ${t.symbol}`} onClick={() => rm.mutate(t.symbol)}>Stop</button></td>
            </tr>))}</tbody>
          </table></div>
        )}
        <div className="track-foot">
          <Job className="job--inline" label="Snapshot all now" start="/api/scorecard/snapshot" status="/api/scorecard/snapshot/status" disabled={activeN === 0} />
          <span className="note">{activeN === 0 ? "Snapshots need at least one stock whose tracking period is still running." : `Writes today's calls for the ${activeN} active stock${activeN === 1 ? "" : "s"} now, instead of waiting for the next data refresh.`}</span>
        </div>
      </Card>

      <div className="toolbar">
        <Seg label="Call type" options={["All", "Verdict card", "Checklist tier", "Next-day model", "Backtest rule"] as const} value={kind} onChange={setKind} />
        <Seg label="Status" options={["All", "Graded", "Waiting"] as const} value={status} onChange={setStatus} />
        <input className="toolbar__filter" aria-label="Filter by symbol" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by symbol" />
        <span className="toolbar__end muted" style={{ fontSize: 13 }}>{rows.length} call{rows.length === 1 ? "" : "s"}</span>
      </div>
      <Card flush>
        <div className="table-wrap"><table className="table">
          <thead><tr><th>Date</th><th>Stock</th><th>Call type</th><th>Call</th><th className="right">Price then</th><th>Horizon</th><th className="right">What happened</th><th className="right"><Term>Against NIFTYBEES</Term></th><th className="right">Result</th></tr></thead>
          <tbody>{rows.map((r) => (<tr key={r.id}><td className="secondary">{r.date}</td><td className="name"><Link to={`/stocks/${encodeURIComponent(r.symbol)}`}>{base(r.symbol)}</Link></td><td className="secondary">{kindLabel(r.kind)}</td><td>{CALL_WORD[r.call] ?? r.call}</td><td className="right">{money(r.price_at)}</td><td className="secondary">{r.horizon_days} day{r.horizon_days === 1 ? "" : "s"}</td><td className="right">{r.ret_pct != null ? <Change value={r.ret_pct} decimals={1} /> : <span className="muted">Pending</span>}</td><td className="right">{r.ret_pct != null && r.bm_ret_pct != null ? <Change value={r.ret_pct - r.bm_ret_pct} decimals={1} /> : ""}</td><td className="right">{r.outcome == null ? <Pill>Waiting</Pill> : r.outcome === "right" ? <Pill kind="gain">Right</Pill> : r.outcome === "wrong" ? <Pill kind="loss">Wrong</Pill> : <Pill>Not scored</Pill>}</td></tr>))}
            {rows.length === 0 && <tr><td colSpan={9} className="muted">No calls match.</td></tr>}</tbody>
        </table></div>
      </Card>
      {sc.data?.rules && <p className="note">{Object.values(sc.data.rules).join(" ")} Rows can never be edited or deleted.</p>}
    </>
  );
}

export function Journal() {
  const j = useQuery({ queryKey: ["journal"], queryFn: () => api.get<{ rows: any[] }>("/api/journal") });
  const [filter, setFilter] = useState("");
  const rows = (j.data?.rows ?? []).filter((r) => !filter || String(r.symbol).toLowerCase().includes(filter.toLowerCase()));
  return (
    <>
      <PageHead title="Journal" sub="Every signal the app raised, with the price at the time. Your own notes live on each stock's Research tab." actions={<input aria-label="Filter by symbol" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by symbol" style={{ height: 40, padding: "0 12px", border: "1px solid var(--line)", borderRadius: 10, background: "var(--surface)" }} />} />
      <SubNav items={RESEARCH} />
      {j.isLoading && <SkeletonCard lines={8} />}{j.isError && <ErrorBox error={j.error} />}
      <Card flush>
        <div className="table-wrap"><table className="table">
          <thead><tr><th>When</th><th>Stock</th><th>What happened</th><th className="right">Price</th><th>Detail</th></tr></thead>
          <tbody>{rows.map((r, i) => (<tr key={i}><td className="secondary">{String(r.when).slice(0, 16)}</td><td className="name"><Link to={`/stocks/${encodeURIComponent(r.symbol)}`}>{base(r.symbol)}</Link></td><td>{signalLabel(r.event)}</td><td className="right">{money(r.price)}</td><td className="secondary" style={{ maxWidth: 420 }}>{r.detail || r.action || ""}</td></tr>))}
            {rows.length === 0 && !j.isLoading && <tr><td colSpan={5} className="muted">Nothing yet. Signals appear after a data refresh.</td></tr>}</tbody>
        </table></div>
      </Card>
      <p className="note">{NOTE}</p>
    </>
  );
}
