import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { localDate, money, pct, signed } from "../lib/format";
import { Card, Change, ErrorBox, PageHead, SkeletonCard, Sparkline, Stat } from "../components/ui";
import { RecordsTable } from "../components/RecordsTable";
import { StockPicker, type PickerHit } from "../components/StockPicker";

/* eslint-disable @typescript-eslint/no-explicit-any */
export default function Funds() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("name") ?? "");
  const funds = useQuery({ queryKey: ["funds"], staleTime: 5 * 60_000, queryFn: () => api.get<any>("/api/funds") });
  const search = useQuery({ queryKey: ["mf-search", q], queryFn: () => api.get<{ results: any[] }>(`/api/mf/search?q=${encodeURIComponent(q)}`), enabled: q.trim().length >= 3, retry: false });
  const sips = useQuery({ queryKey: ["sips"], queryFn: () => api.get<any>("/api/sips") });
  const lumps = useQuery({ queryKey: ["mf-holdings"], queryFn: () => api.get<any>("/api/mf/holdings") });
  const refresh = () => { ["funds", "sips", "mf-holdings", "watchlist"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })); };
  const add = useMutation({ mutationFn: (r: any) => api.post("/api/mf/add", { scheme_code: Number(r.scheme_code ?? r.schemeCode), label: r.name ?? r.schemeName ?? "" }), meta: { ok: "Fund added. Its NAV history is downloading." }, onSuccess: () => { setQ(""); refresh(); } });
  // Arriving from search with ?add=<scheme code>: track it straight away.
  // Keyed on params, not mount: search can link here while /funds is open.
  useEffect(() => { const code = params.get("add"); if (code) { add.mutate({ scheme_code: Number(code), name: params.get("name") ?? "" }); setParams({}, { replace: true }); } }, [params]); // eslint-disable-line react-hooks/exhaustive-deps
  const [sip, setSip] = useState({ scheme_code: "", amount: "", day_of_month: "5", start_date: localDate() });
  const addSip = useMutation({ mutationFn: () => api.post("/api/sips", { scheme_code: Number(sip.scheme_code), amount: Number(sip.amount), day_of_month: Number(sip.day_of_month), start_date: sip.start_date }), meta: { ok: "SIP added, simulated against real NAV history" }, onSuccess: refresh });
  const [lu, setLu] = useState({ scheme_code: "", units: "", buy_nav: "", buy_date: localDate() });
  const addLump = useMutation({ mutationFn: () => api.post("/api/mf/holdings", { scheme_code: Number(lu.scheme_code), units: Number(lu.units), buy_nav: Number(lu.buy_nav), buy_date: lu.buy_date }), meta: { ok: "Fund holding added" }, onSuccess: refresh });

  if (funds.isLoading) return (<><PageHead title="Mutual funds" /><SkeletonCard lines={8} /></>);
  if (funds.isError) return (<><PageHead title="Mutual funds" /><ErrorBox error={funds.error} /></>);
  const list: any[] = funds.data.funds ?? [];
  const t = funds.data.totals ?? {}, bm = funds.data.benchmark?.returns ?? {};
  const options = list.map((f): PickerHit => ({ symbol: String(f.scheme_code), name: f.label, bare: true }));
  const fundPicker = (id: string, value: string, onChange: (v: string) => void) => <StockPicker id={id} label="Fund" placeholder="Search your funds" value={value} onChange={onChange} options={options} nameSearch={false} required />;
  const sub = (fn: () => void) => (e: FormEvent) => { e.preventDefault(); fn(); };

  return (
    <>
      <PageHead title="Mutual funds" sub="Your funds, SIPs, and how they compare with simply holding the index" />
      <div className="grid grid-4">
        <div className="card"><Stat big label="Funds tracked" value={t.funds ?? 0} /></div>
        <div className="card"><Stat big label="Invested, SIP and lump sum" value={money(t.invested, 0)} detail={<span className="muted">SIP {money(t.sip_invested, 0)}, lump {money(t.lumpsum_invested, 0)}</span>} /></div>
        <div className="card"><Stat big label="Value today" value={money(t.value, 0)} detail={<span className={(t.pnl ?? 0) >= 0 ? "gain" : "loss"}>{signed(t.pnl)}</span>} /></div>
        <div className="card"><Stat big label="NIFTYBEES, 1 year" value={<Change value={bm["1y"]} decimals={1} />} detail={<span className="muted">The fee-free bar to beat</span>} /></div>
      </div>

      <Card title="Add a fund" sub="Official AMFI NAVs. Track direct-growth plans. Regular plans carry a distributor fee.">
        <div className="f" style={{ maxWidth: 560, marginTop: 8 }}><label htmlFor="mfq" className="sr-only">Fund name</label><input id="mfq" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Type 3 or more letters, like parag parikh flexi" /></div>
        {search.isError && <div className="note loss" style={{ marginTop: 8 }}>{(search.error as Error).message}</div>}
        {search.data?.results.slice(0, 8).map((r: any) => (<div className="kv" key={r.scheme_code ?? r.schemeCode}><span>{r.name ?? r.schemeName}</span><button className="btn" style={{ height: 32 }} disabled={add.isPending} onClick={() => add.mutate(r)}>Track</button></div>))}
      </Card>

      <Card flush title="Tracked funds" sub="Click a fund to open its page">
        <div className="table-wrap"><table className="table">
          <thead><tr><th>Fund</th><th className="right">NAV</th><th className="right">1M</th><th className="right">1Y</th><th className="right">3Y, a year</th><th className="right">Rolling 1Y, median</th><th className="right">Rolling 1Y, worst</th><th className="right">Against NIFTYBEES</th><th className="right">Max drawdown</th><th className="right">90 days</th></tr></thead>
          <tbody>
            {list.map((f) => { const s = f.stats; return (
              <tr key={f.id} className="clickable" onClick={() => navigate(`/funds/${f.scheme_code}`)}><td className="name"><Link to={`/funds/${f.scheme_code}`} onClick={(e) => e.stopPropagation()}>{f.label}</Link><small>{f.error ? f.error : s ? `NAV of ${s.nav_date}` : "No NAV history yet. Refresh data."}</small></td>
                <td className="right">{money(s?.latest_nav)}</td><td className="right"><Change value={s?.returns?.["1m"]} decimals={1} /></td><td className="right"><Change value={s?.returns?.["1y"]} decimals={1} /></td>
                <td className="right">{s?.returns?.["3y"] != null ? pct((Math.pow(1 + s.returns["3y"] / 100, 1 / 3) - 1) * 100, 1) : "\u2014"}</td>
                <td className="right"><Change value={s?.rolling?.["1y"]?.median} decimals={1} /></td><td className="right"><Change value={s?.rolling?.["1y"]?.worst ?? s?.rolling?.["1y"]?.min} decimals={1} /></td>
                <td className="right"><Change value={f.vs_index_1y} decimals={1} /></td><td className="right"><Change value={s?.max_drawdown} decimals={1} /></td><td className="right"><Sparkline values={s?.spark ?? []} /></td></tr>); })}
            {list.length === 0 && <tr><td colSpan={10} className="muted">No funds yet. Search above and pick the direct-growth plan.</td></tr>}
          </tbody>
        </table></div>
      </Card>

      <div className="callout"><span><b>How to read the table.</b> Rolling 1Y looks at every one-year holding period in the fund's history. The median is what a typical year gave, and the worst is what an unlucky entry gave. Against NIFTYBEES is the fund's 1Y return minus the index ETF's, the fee-free alternative it has to beat.</span></div>

      <div className="row" id="sips">
        <Card flush className="grow-2" title="SIPs" sub="Simulated against real NAV history, giving a true XIRR">
          <RecordsTable rows={sips.data?.sips ?? []} symbolKey="" empty="No SIPs yet." />
          <form onSubmit={sub(() => addSip.mutate())} className="form-row" style={{ padding: "14px 20px 18px", borderTop: "1px solid var(--line)" }}>
            {fundPicker("sf", sip.scheme_code, (scheme_code) => setSip((x) => ({ ...x, scheme_code })))}
            <div className="f"><label htmlFor="sa">Amount a month</label><input id="sa" type="number" value={sip.amount} onChange={(e) => setSip({ ...sip, amount: e.target.value })} required /></div>
            <div className="f"><label htmlFor="sdm">Day, 1 to 28</label><input id="sdm" type="number" min={1} max={28} value={sip.day_of_month} onChange={(e) => setSip({ ...sip, day_of_month: e.target.value })} /></div>
            <div className="f"><label htmlFor="sst">Started</label><input id="sst" type="date" value={sip.start_date} onChange={(e) => setSip({ ...sip, start_date: e.target.value })} /></div>
            <button className="btn btn--primary" disabled={addSip.isPending}>Add SIP</button>
          </form>
          {addSip.isError && <div style={{ padding: "0 20px 16px" }}><ErrorBox error={addSip.error} /></div>}
        </Card>
        <Card flush className="grow" title="Lump-sum holdings" sub="Units you bought outright">
          <RecordsTable rows={lumps.data?.holdings ?? []} symbolKey="" empty="None yet." />
          <form onSubmit={sub(() => addLump.mutate())} style={{ display: "flex", flexDirection: "column", gap: 10, padding: "14px 20px 18px", borderTop: "1px solid var(--line)" }}>
            {fundPicker("lf", lu.scheme_code, (scheme_code) => setLu((x) => ({ ...x, scheme_code })))}
            <div className="form-row"><div className="f"><label htmlFor="lun">Units</label><input id="lun" type="number" step="any" value={lu.units} onChange={(e) => setLu({ ...lu, units: e.target.value })} required /></div><div className="f"><label htmlFor="lnv">Buy NAV</label><input id="lnv" type="number" step="any" value={lu.buy_nav} onChange={(e) => setLu({ ...lu, buy_nav: e.target.value })} required /></div></div>
            <button className="btn" disabled={addLump.isPending}>Add holding</button>
            {addLump.isError && <ErrorBox error={addLump.error} />}
          </form>
        </Card>
      </div>
    </>
  );
}
