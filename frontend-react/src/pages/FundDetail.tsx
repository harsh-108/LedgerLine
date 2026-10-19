import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { getDetail, DETAIL_STALE_MS } from "../lib/detail";
import { money, pct, signed } from "../lib/format";
import { Card, Change, ErrorBox, Pill, Seg, SkeletonCard, Stat } from "../components/ui";
import { SeriesChart } from "../components/SeriesChart";
import { RecordsTable } from "../components/RecordsTable";

/* eslint-disable @typescript-eslint/no-explicit-any */
const RANGES = ["6M", "1Y", "3Y", "5Y", "Max"] as const;
const DAYS: Record<(typeof RANGES)[number], number> = { "6M": 126, "1Y": 252, "3Y": 756, "5Y": 1260, Max: 1e9 };
const annual = (totalPct: number | undefined, years: number) => (totalPct == null ? null : (Math.pow(1 + totalPct / 100, 1 / years) - 1) * 100);

export default function FundDetail() {
  const { scheme = "" } = useParams();
  const [range, setRange] = useState<(typeof RANGES)[number]>("3Y");
  const [sip, setSip] = useState(5000);
  const [years, setYears] = useState(3);
  const d = useQuery({ queryKey: ["fund", scheme], staleTime: 5 * 60_000, queryFn: () => api.get<any>(`/api/mf/${scheme}`), retry: false });
  const list = useQuery({ queryKey: ["funds"], staleTime: 5 * 60_000, queryFn: () => api.get<any>("/api/funds") });
  const bench = useQuery({ queryKey: ["detail", "NIFTYBEES.NS"], queryFn: () => getDetail("NIFTYBEES.NS"), retry: false, staleTime: DETAIL_STALE_MS });
  const meta = (list.data?.funds ?? []).find((f: any) => String(f.scheme_code) === String(scheme));
  const nav: { time: string; value: number }[] = d.data?.nav ?? [];

  const series = useMemo(() => {
    const cut = nav.slice(-DAYS[range]); if (cut.length < 2) return [];
    const from = cut[0].time, b0 = cut[0].value;
    const out = [{ name: "This fund", color: "--action", data: cut.map((x) => ({ time: x.time, value: +((x.value / b0 - 1) * 100).toFixed(2) })) }];
    const bc = (bench.data?.candles ?? []).filter((c: any) => c.time >= from);
    if (bc.length > 1) out.push({ name: "NIFTYBEES, the index you could hold instead", color: "--teal", data: bc.map((c: any) => ({ time: c.time, value: +((c.close / bc[0].close - 1) * 100).toFixed(2) })) });
    return out;
  }, [nav, range, bench.data]);

  // "If you had invested": a monthly SIP replayed on the real NAV history.
  const replay = useMemo(() => {
    if (nav.length < 30) return null;
    const start = new Date(nav[nav.length - 1].time); start.setFullYear(start.getFullYear() - years);
    let units = 0, put = 0, month = -1;
    for (const p of nav) { const t = new Date(p.time); if (t < start) continue; const m = t.getFullYear() * 12 + t.getMonth(); if (m !== month && put < sip * years * 12) { month = m; units += sip / p.value; put += sip; } }
    if (!put) return null;
    const worth = units * nav[nav.length - 1].value;
    return { put, worth, gainPct: (worth / put - 1) * 100, short: new Date(nav[0].time) > start };
  }, [nav, sip, years]);

  if (d.isLoading) return (<><h1 className="display" style={{ fontSize: 28 }}>Mutual fund</h1><SkeletonCard lines={3} /><SkeletonCard lines={8} /></>);
  if (d.isError) return (<><h1 className="display" style={{ fontSize: 28 }}>{meta?.label ?? "Mutual fund"}</h1><ErrorBox error={d.error} /><p className="note">NAV history downloads with the next data refresh. Use the refresh button in the ribbon, then come back.</p><Link className="btn" to="/funds">Back to funds</Link></>);

  const st = d.data.detail ?? {}; const r = st.returns ?? {}; const roll = st.rolling ?? {};
  const pos = d.data.position;
  const rows = [["1Y", r["1y"], 1], ["3Y", r["3y"], 3], ["5Y", r["5y"], 5]] as const;
  const bm = list.data?.benchmark?.returns ?? {};

  return (
    <>
      <div className="pagehead">
        <div>
          <div className="muted" style={{ fontSize: 13 }}><Link to="/funds">Mutual Funds</Link> / {meta?.label ?? scheme}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginTop: 6 }}><h1>{meta?.label ?? `Scheme ${scheme}`}</h1><Pill>Scheme {scheme}</Pill>{/direct/i.test(meta?.label ?? "") && <Pill>Direct plan</Pill>}{/regular/i.test(meta?.label ?? "") && <Pill kind="guide">Regular plan, carries a distributor fee</Pill>}</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginTop: 8, flexWrap: "wrap" }}><span className="display" style={{ fontSize: 38 }}>{money(st.latest_nav)}</span><span style={{ fontSize: 16 }}><Change value={st.day_pct} /></span><span className="muted" style={{ fontSize: 13 }}>NAV of {st.nav_date}</span></div>
        </div>
        <div className="pagehead__actions"><Link className="btn" to="/funds">All funds</Link><Link className="btn btn--primary" to="/funds#sips">Add a SIP or holding</Link></div>
      </div>

      <div className="row" style={{ alignItems: "flex-start" }}>
        <div className="grow-2" style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <Card>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 10 }}><Seg label="Range" options={RANGES} value={range} onChange={setRange} /><span className="secondary" style={{ fontSize: 13 }}>Growth in percent, both starting at zero</span></div>
            <SeriesChart series={series} height={300} guides={[0]} />
          </Card>
          <Card flush title="Returns" sub="Yearly rate for periods over a year">
            <div className="table-wrap"><table className="table"><thead><tr><th /><th className="right">1M</th><th className="right">6M</th>{rows.map(([l]) => <th key={l} className="right">{l}</th>)}<th className="right">Since {String(st.since ?? "").slice(0, 4)}</th></tr></thead>
              <tbody>
                <tr><td className="name">This fund</td><td className="right"><Change value={r["1m"]} decimals={1} /></td><td className="right"><Change value={r["6m"]} decimals={1} /></td>{rows.map(([l, v, y]) => <td key={l} className="right"><Change value={annual(v, y)} decimals={1} /></td>)}<td className="right"><Change value={st.cagr} decimals={1} /></td></tr>
                <tr><td className="secondary">NIFTYBEES</td><td className="right"><Change value={bm["1m"]} decimals={1} /></td><td className="right"><Change value={bm["6m"]} decimals={1} /></td>{rows.map(([l, , y]) => <td key={l} className="right"><Change value={annual(bm[l.toLowerCase()], y)} decimals={1} /></td>)}<td className="right muted">&mdash;</td></tr>
              </tbody></table></div>
          </Card>
          <Card title="What a typical year looked like" sub="Every possible holding period in this fund's history, not only the latest one">
            <div className="grid grid-2" style={{ marginTop: 14 }}>
              {([["1y", "Any 1 year"], ["3y", "Any 3 years, yearly rate"]] as const).map(([k, l]) => { const x = roll[k]; return (<div key={k} style={{ padding: 16, borderRadius: 12, background: "var(--ground)" }}><div style={{ fontWeight: 600 }}>{l}</div>{x ? (<><div className="kv" style={{ borderTop: "none" }}><span>Typical (median)</span><span><Change value={x.median} decimals={1} /></span></div><div className="kv"><span>Unluckiest entry</span><span><Change value={x.worst} decimals={1} /></span></div><div className="kv"><span>Luckiest entry</span><span><Change value={x.best} decimals={1} /></span></div><div className="kv"><span>Ended with a gain</span><span>{x.positive_pct}% of {x.windows} periods</span></div></>) : <div className="note" style={{ marginTop: 8 }}>Not enough history yet.</div>}</div>); })}
            </div>
            <p className="note">A single "1Y return" depends on the day you looked. This range does not.</p>
          </Card>
        </div>

        <div className="grow" style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <Card title="Fund facts"><div style={{ marginTop: 8 }}>
            <div className="kv"><span>Against NIFTYBEES, 1 year</span><span><Change value={d.data.vs_index_1y} decimals={1} /></span></div>
            <div className="kv"><span>Biggest fall from a peak</span><span><Change value={st.max_drawdown} decimals={1} /></span></div>
            <div className="kv"><span>NAV history since</span><span>{st.since}</span></div>
            <div className="kv"><span>NAVs stored</span><span>{st.n_navs}</span></div>
          </div><p className="note">Expense ratio, fund size, manager and holdings are not in the free AMFI feed, so they are not shown. Check the fund house's factsheet for those.</p></Card>

          <Card title="If you had invested" sub="A monthly SIP replayed on the real NAV history">
            <div className="form-row" style={{ marginTop: 12 }}>
              <div className="f"><label htmlFor="sipamt">Monthly amount</label><input id="sipamt" type="number" step={500} value={sip} onChange={(e) => setSip(Number(e.target.value) || 0)} /></div>
              <div className="f"><label htmlFor="sipyrs">For how long</label><select id="sipyrs" value={years} onChange={(e) => setYears(Number(e.target.value))}>{[1, 3, 5, 10].map((y) => <option key={y} value={y}>{y} year{y === 1 ? "" : "s"}</option>)}</select></div>
            </div>
            {replay && (<div style={{ marginTop: 14, padding: 16, borderRadius: 12, background: "var(--action-tint)" }}><div className="secondary" style={{ fontSize: 13.5 }}>You put in {money(replay.put, 0)}. It would be worth</div><div className="display" style={{ fontSize: 26, marginTop: 2 }}>{money(replay.worth, 0)} <span className={replay.gainPct >= 0 ? "gain" : "loss"} style={{ fontSize: 14 }}>{pct(replay.gainPct, 1)}</span></div><div className="note" style={{ marginTop: 4 }}>{replay.short ? "The stored history is shorter than this period, so it starts from the first NAV. " : ""}Past returns do not predict future returns.</div></div>)}
          </Card>

          {pos && (<Card title="Your position"><div className="grid grid-2" style={{ marginTop: 12 }}><Stat label="Invested" value={money(pos.invested, 0)} /><Stat label="Value today" value={money(pos.value ?? pos.current, 0)} /><Stat label="Gain" value={<span className={(pos.pnl ?? 0) >= 0 ? "gain" : "loss"}>{signed(pos.pnl)}</span>} />{pos.xirr != null && <Stat label="XIRR" value={pct(pos.xirr, 1)} />}</div></Card>)}
          {(d.data.sips ?? []).length > 0 && <Card flush title="Your SIPs in this fund"><RecordsTable rows={d.data.sips} symbolKey="" /></Card>}
          {(d.data.holdings ?? []).length > 0 && <Card flush title="Your lump-sum holdings"><RecordsTable rows={d.data.holdings} symbolKey="" /></Card>}
        </div>
      </div>
    </>
  );
}
