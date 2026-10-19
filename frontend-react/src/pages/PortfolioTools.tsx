import { useMemo, useState, type FormEvent, type InputHTMLAttributes } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { getDetail } from "../lib/detail";
import { base, localDate, money, signed } from "../lib/format";
import { Card, ErrorBox, PageHead } from "../components/ui";
import { SubNav } from "../components/Section";
import { PORTFOLIO } from "../lib/nav";
import { toast } from "../components/Toast";
import { InfoTip } from "../components/InfoTip";
import { StockPicker } from "../components/StockPicker";

/* eslint-disable @typescript-eslint/no-explicit-any */
const today = () => localDate();
function F({ id, label, ...rest }: { id: string; label: string } & InputHTMLAttributes<HTMLInputElement>) {
  return <div className="f"><label htmlFor={id}>{label}</label><input id={id} {...rest} /></div>;
}

export default function PortfolioTools() {
  const qc = useQueryClient();
  const p = useQuery({ queryKey: ["portfolio"], queryFn: () => api.get<any>("/api/portfolio") });
  const holdings: any[] = p.data?.holdings ?? [];
  const total = p.data?.totals?.current ?? 0;
  const done = () => { qc.invalidateQueries({ queryKey: ["portfolio"] }); qc.invalidateQueries({ queryKey: ["home"] }); qc.invalidateQueries({ queryKey: ["tape"] }); };

  // add
  const [a, setA] = useState({ symbol: "", qty: "", buy_price: "", buy_date: today(), thesis: "" });
  const add = useMutation({ mutationFn: () => api.post("/api/portfolio", { symbol: a.symbol.trim().toUpperCase(), qty: Number(a.qty), buy_price: Number(a.buy_price), buy_date: a.buy_date, thesis: a.thesis || null }), meta: { ok: (d: any) => `Added ${d.symbol}` }, onSuccess: () => { setA({ symbol: "", qty: "", buy_price: "", buy_date: today(), thesis: "" }); done(); } });
  // sell
  const [sym, setSym] = useState("");
  const sel = holdings.find((h) => h.Symbol === sym);
  const [s, setS] = useState({ qty: "", price: "", date: today() });
  const lots = useQuery({ queryKey: ["detail", sym], queryFn: () => getDetail(sym), enabled: !!sym, select: (d) => (d.position?.lots ?? []) as { id: number; qty: number; buy_price: number; buy_date: string }[] });
  const [lot, setLot] = useState<number | null>(null);
  const lotId = lot ?? lots.data?.[0]?.id ?? sel?.ids?.[0];
  const sell = useMutation({ mutationFn: () => api.post("/api/sell", { lot_id: lotId, qty: Number(s.qty), price: Number(s.price), date: s.date }), meta: { ok: () => `Sold ${s.qty} x ${base(sym)} recorded` }, onSuccess: () => { setS({ qty: "", price: "", date: today() }); setSym(""); done(); } });
  // dividends
  const [dv, setDv] = useState({ symbol: "", amount: "", date: today() });
  const addDiv = useMutation({ mutationFn: () => api.post("/api/dividends", { symbol: dv.symbol, amount: Number(dv.amount), date: dv.date }), meta: { ok: "Dividend recorded" }, onSuccess: () => { setDv({ symbol: "", amount: "", date: today() }); done(); } });
  const delDiv = useMutation({ mutationFn: (id: number) => api.del(`/api/dividends/${id}`), meta: { ok: "Dividend removed" }, onSuccess: done });
  // import: a CSV with columns symbol, qty, buy_price, buy_date, thesis
  const importCsv = async (file: File) => {
    const lines = (await file.text()).split(/\r?\n/).filter((l) => l.trim());
    const head = lines[0].toLowerCase().split(",").map((h) => h.trim().replace(/"/g, ""));
    const col = (names: string[]) => head.findIndex((h) => names.includes(h));
    const ci = { s: col(["symbol", "ticker"]), q: col(["qty", "quantity"]), p: col(["buy_price", "avg cost", "price", "buy price"]), d: col(["buy_date", "since", "date"]), t: col(["thesis", "note"]) };
    if (ci.s < 0 || ci.q < 0 || ci.p < 0) { toast("The CSV needs symbol, qty and buy_price columns", "err"); return; }
    let added = 0;
    for (const line of lines.slice(1)) { const c = line.split(",").map((x) => x.trim().replace(/^"|"$/g, "")); try { await api.post("/api/portfolio", { symbol: c[ci.s].toUpperCase(), qty: Number(c[ci.q]), buy_price: Number(c[ci.p]), buy_date: ci.d >= 0 ? c[ci.d] || null : null, thesis: ci.t >= 0 ? c[ci.t] || null : null }); added++; } catch { /* skip bad rows */ } }
    toast(`Imported ${added} holding${added === 1 ? "" : "s"}`, added ? "ok" : "err"); done();
  };
  // position size
  const [ps, setPs] = useState({ capital: "500000", risk_pct: "1", entry: "", stop: "" });
  const size = useQuery({ queryKey: ["possize", ps], queryFn: () => api.get<any>(`/api/position-size?capital=${ps.capital}&risk_pct=${ps.risk_pct}&entry=${ps.entry}&stop=${ps.stop}`), enabled: !!(Number(ps.entry) && Number(ps.stop)), retry: false });
  // what-if (worked out here, nothing is saved)
  const [wi, setWi] = useState({ symbol: "", qty: "", price: "" });
  const whatIf = useMemo(() => {
    const add_ = Number(wi.qty) * Number(wi.price); if (!add_ || !total) return null;
    const cur = holdings.find((h) => h.Symbol === wi.symbol.toUpperCase())?.Current ?? 0;
    return { before: (cur / total) * 100, after: ((cur + add_) / (total + add_)) * 100 };
  }, [wi, holdings, total]);
  // rebalance
  const [targets, setTargets] = useState<Record<string, string>>({});
  const eq = () => setTargets(Object.fromEntries(holdings.map((h) => [h.Symbol, (100 / holdings.length).toFixed(1)])));

  const sub = (fn: () => void) => (e: FormEvent) => { e.preventDefault(); fn(); };

  return (
    <>
      <PageHead title="Portfolio tools" sub="Record what you did, and test what you are about to do" actions={<label className="btn" style={{ cursor: "pointer" }}>Import CSV<input type="file" accept=".csv,text/csv" style={{ display: "none" }} onChange={(e) => e.target.files?.[0] && importCsv(e.target.files[0])} /></label>} />
      <SubNav items={PORTFOLIO} />
      {p.isError && <ErrorBox error={p.error} />}
      {/* Three independent stacks, not a 3x2 grid: each column flows at its own
          height, so a short card never leaves a gap under it. */}
      <div className="cols-3">
        <div className="stack">
          <Card title="Add a holding">
            <form onSubmit={sub(() => add.mutate())} style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
              <StockPicker id="as" label="Stock" value={a.symbol} onChange={(symbol) => setA((x) => ({ ...x, symbol }))} required />
              <div className="form-row"><F id="aq" label="Quantity" type="number" step="any" value={a.qty} onChange={(e) => setA({ ...a, qty: e.target.value })} required /><F id="ap" label="Buy price" type="number" step="any" value={a.buy_price} onChange={(e) => setA({ ...a, buy_price: e.target.value })} required /></div>
              <F id="ad" label="Buy date" type="date" value={a.buy_date} onChange={(e) => setA({ ...a, buy_date: e.target.value })} />
              <F id="at" label="Why this buy? Shown back to you at sell time" value={a.thesis} onChange={(e) => setA({ ...a, thesis: e.target.value })} />
              {add.isError && <ErrorBox error={add.error} />}
              <button className="btn btn--primary" disabled={add.isPending}>Add holding</button>
            </form>
          </Card>

          <Card title="Rebalance helper" action={<button className="btn" onClick={eq}>Equal weight</button>}>
            <div style={{ marginTop: 10 }}>
              {holdings.map((h) => { const t = Number(targets[h.Symbol]); const delta = t ? (t / 100) * total - (h.Current ?? 0) : null; return (
                <div key={h.Symbol} className="kv"><span>{base(h.Symbol)} <span className="muted">now {h["Weight %"]}%</span></span>
                  <span style={{ display: "flex", alignItems: "center", gap: 8 }}><input aria-label={`Target for ${h.Symbol}`} type="number" step="any" value={targets[h.Symbol] ?? ""} onChange={(e) => setTargets({ ...targets, [h.Symbol]: e.target.value })} placeholder="%" style={{ width: 64, height: 32, border: "1px solid var(--line)", borderRadius: 8, padding: "0 8px", textAlign: "right", background: "var(--surface)" }} />
                    <span className={delta == null ? "muted" : delta >= 0 ? "gain" : "loss"} style={{ width: 110 }}>{delta == null ? "\u2014" : `${delta >= 0 ? "Buy" : "Sell"} ${money(Math.abs(delta), 0)}`}</span></span></div>); })}
              {holdings.length === 0 && <div className="note">Add holdings first.</div>}
            </div>
            <p className="note">A worksheet. Nothing is executed.</p>
          </Card>
        </div>
        <div className="stack">
          <Card title="Sell">
            <form onSubmit={sub(() => sell.mutate())} style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
              <StockPicker id="ss" label="Holding" placeholder="Search your holdings" value={sym} onChange={(v) => { setSym(v); setLot(null); }} required
                options={holdings.map((h) => ({ symbol: h.Symbol, name: `${h.Qty} shares at ${money(h["Avg cost"])}`, right: h.Current != null ? money(h.Current, 0) : undefined }))} />
              {sel?.thesis && <div className="callout"><span><b>You bought because:</b> {sel.thesis}</span></div>}
              <div className="form-row"><F id="sq" label="Quantity" type="number" step="any" value={s.qty} onChange={(e) => setS({ ...s, qty: e.target.value })} required /><F id="sp" label="Sell price" type="number" step="any" value={s.price} onChange={(e) => setS({ ...s, price: e.target.value })} required /></div>
              <F id="sd" label="Sell date" type="date" value={s.date} onChange={(e) => setS({ ...s, date: e.target.value })} />
              {sel && Number(s.qty) > 0 && Number(s.price) > 0 && <div className="kv"><span>Gain on this sale</span><span className={Number(s.price) >= sel["Avg cost"] ? "gain" : "loss"}>{signed((Number(s.price) - sel["Avg cost"]) * Number(s.qty))}</span></div>}
              {(lots.data?.length ?? 0) > 1 && <div className="f"><label htmlFor="slot">Which lot</label><select id="slot" value={lotId ?? ""} onChange={(e) => setLot(Number(e.target.value))}>{lots.data!.map((l) => <option key={l.id} value={l.id}>{l.qty} bought at {money(l.buy_price)} on {l.buy_date}</option>)}</select></div>}
              {sell.isError && <ErrorBox error={sell.error} />}
              <button className="btn btn--primary" disabled={!sel || sell.isPending}>Record sale</button>
            </form>
          </Card>

          <Card title="What-if simulator" sub="Try a hypothetical buy. Nothing is saved.">
            <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
              <StockPicker id="ws" label="Stock" value={wi.symbol} onChange={(symbol) => setWi((x) => ({ ...x, symbol }))} />
              <div className="form-row"><F id="wq" label="Quantity" type="number" value={wi.qty} onChange={(e) => setWi({ ...wi, qty: e.target.value })} /><F id="wp" label="Price" type="number" step="any" value={wi.price} onChange={(e) => setWi({ ...wi, price: e.target.value })} /></div>
              {whatIf && <><div className="kv"><span>Share of portfolio</span><span>{whatIf.before.toFixed(1)}% to {whatIf.after.toFixed(1)}%</span></div>{whatIf.after > 25 && <div className="error">One holding would be {whatIf.after.toFixed(0)}% of your money</div>}</>}
            </div>
          </Card>
        </div>
        <div className="stack">
          <Card title="Position size" sub="Shares such that a stop-loss hit costs only a set part of your capital">
            <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
              <div className="form-row"><F id="pc" label="Capital" type="number" value={ps.capital} onChange={(e) => setPs({ ...ps, capital: e.target.value })} /><F id="pr" label="Risk %" type="number" step="any" value={ps.risk_pct} onChange={(e) => setPs({ ...ps, risk_pct: e.target.value })} /></div>
              <div className="form-row"><F id="pe" label="Entry price" type="number" step="any" value={ps.entry} onChange={(e) => setPs({ ...ps, entry: e.target.value })} /><F id="pst" label="Stop price" type="number" step="any" value={ps.stop} onChange={(e) => setPs({ ...ps, stop: e.target.value })} /></div>
              {size.data && <div style={{ padding: 14, borderRadius: 12, background: "var(--action-tint)" }}><div className="secondary" style={{ fontSize: 13 }}>Buy at most<InfoTip k="__sizer" /></div><div className="display" style={{ fontSize: 26 }}>{size.data.shares} shares</div>{size.data.shares > 0 && <div className="secondary" style={{ fontSize: 13 }}>Worth {money(size.data.outlay, 0)}, {size.data.outlay_pct}% of capital. A stop hit would cost {money(size.data.risk_amount, 0)}.</div>}{size.data.note && <div className="secondary" style={{ fontSize: 13, marginTop: 4 }}>{size.data.note}</div>}</div>}
              {size.isError && <div className="note loss">{(size.error as Error).message}</div>}
            </div>
          </Card>

          <Card title="Dividends received" sub="Cash that price-only gains cannot see">
            <div style={{ marginTop: 8 }}>{(p.data?.dividends ?? []).map((x: any) => (<div className="kv" key={x.id}><span>{base(x.symbol)}, {x.date}</span><span>{money(x.amount, 0)} <button className="btn btn--quiet" style={{ height: 24, padding: "0 4px" }} onClick={() => delDiv.mutate(x.id)}>Remove</button></span></div>))}</div>
            <form onSubmit={sub(() => addDiv.mutate())} style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
              <StockPicker id="ds" label="Holding" placeholder="Search your holdings" value={dv.symbol} onChange={(symbol) => setDv((x) => ({ ...x, symbol }))} required options={holdings.map((h) => ({ symbol: h.Symbol, name: `${h.Qty} shares` }))} />
              <div style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
                <div style={{ flex: 1 }}><F id="da" label="Amount" type="number" step="any" value={dv.amount} onChange={(e) => setDv({ ...dv, amount: e.target.value })} required /></div>
                <button className="btn" style={{ height: 44 }} disabled={addDiv.isPending}>Add</button>
              </div>
            </form>
            {addDiv.isError && <ErrorBox error={addDiv.error} />}
          </Card>
        </div>
      </div>
      {p.data?.realized && <Card title="Realized gains"><pre className="log">{JSON.stringify(p.data.realized, null, 1)}</pre></Card>}
    </>
  );
}
