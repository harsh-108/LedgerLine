import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { base, money, signed } from "../lib/format";
import { CALL_KIND, signalLabel, TIER_LABEL, tierKind } from "../lib/labels";
import type { HomeData } from "../lib/types";
import { Card, Change, ErrorBox, PageHead, Pill, SkeletonCard, Stat } from "../components/ui";
import { PeekLink } from "../components/Peek";

/* eslint-disable @typescript-eslint/no-explicit-any */
export default function Home() {
  const home = useQuery({ queryKey: ["home"], queryFn: () => api.get<HomeData>("/api/home") });
  const tiers = useQuery({ queryKey: ["tiers"], queryFn: () => api.get<any>("/api/tiers"), retry: false });
  const score = useQuery({ queryKey: ["scorecard"], queryFn: () => api.get<any>("/api/scorecard"), retry: false });

  if (home.isLoading) return (<><PageHead title="Home" sub="Loading your overview" /><div className="grid grid-4">{[0, 1, 2, 3].map((i) => <SkeletonCard key={i} lines={2} />)}</div><SkeletonCard lines={6} /></>);
  if (home.isError) return (<><PageHead title="Home" /><ErrorBox error={home.error} /></>);
  const d = home.data!;
  const p = d.portfolio;
  const changes: any[] = tiers.data?.changes ?? [];
  const summary: any[] = (score.data?.summary ?? []).filter((s: any) => s.total > 0);

  return (
    <>
      <PageHead title="Home" sub={d.data_through ? `Data through ${d.data_through}` : "No price data yet. Use the refresh button in the ribbon."}
        actions={<><Link className="btn" to="/screener">Screen stocks</Link><Link className="btn" to="/research/backtest">Test a strategy</Link><Link className="btn" to="/research/ai-lab">Factor rankings</Link></>} />

      <div className="grid grid-4">
        <div className="card"><Stat big label="Your stocks today" value={<><span className="gain">{d.advancing} up</span>, <span className="loss">{d.declining} down</span></>} /></div>
        <div className="card"><Stat big label="Signals today" value={d.signals_today} detail={<Link to="/research/journal" className="muted">See the journal</Link>} /></div>
        <div className="card"><Stat big label="Portfolio value" value={p ? money(p.current, 0) : "Not set up"} detail={p ? <span className="muted">Invested {money(p.invested, 0)}</span> : <Link to="/portfolio/tools" className="muted">Add your first holding</Link>} /></div>
        <div className="card"><Stat big label="Total gain" value={p ? <span className={p.pnl >= 0 ? "gain" : "loss"}>{signed(p.pnl)}</span> : "\u2014"} detail={p?.day_pct != null ? <>Today <Change value={p.day_pct} /></> : undefined} /></div>
      </div>

      <div className="row">
        <Card flush className="grow-2" title="Today's movers" action={<Link to="/watchlists" className="btn btn--quiet">Watchlists</Link>}>
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Stock</th><th className="right">Price</th><th className="right">Today</th></tr></thead>
            <tbody>
              {d.movers.map((m) => (<tr key={m.symbol}><td className="name"><PeekLink symbol={m.symbol}>{m.symbol}</PeekLink></td><td className="right">{money(m.last)}</td><td className="right"><Change value={m.pct} /></td></tr>))}
              {d.movers.length === 0 && <tr><td colSpan={3} className="muted">No moves yet. Add stocks to a watchlist, then refresh data.</td></tr>}
            </tbody>
          </table></div>
        </Card>
        {/* Two short lists stacked beside the table; the second one stretches so the column ends level with it. */}
        <div className="grow stack">
          <Card title="Results this week" sub="Companies in your watchlist reporting soon">
            <div style={{ marginTop: 8 }}>
              {d.earnings_week.map((e) => (<div className="kv" key={e.symbol + e.date}><span><PeekLink symbol={e.symbol}>{e.symbol}</PeekLink></span><span>{e.date}</span></div>))}
              {d.earnings_week.length === 0 && <div className="note">Nothing scheduled in the next 7 days.</div>}
            </div>
          </Card>
          <Card className="grow" title="Latest journal entries" action={<Link to="/research/journal" className="btn btn--quiet">Journal</Link>}>
            <div style={{ marginTop: 8 }}>
              {d.journal.map((j, i) => (<div className="kv" key={i}><span><Pill kind="action">{base(j.symbol)}</Pill> {signalLabel(j.signal)}</span><span className="muted">{String(j.created).slice(0, 10)}</span></div>))}
              {d.journal.length === 0 && <div className="note">Signals and your notes will show up here.</div>}
            </div>
          </Card>
        </div>
      </div>

      <div className="grid grid-2">
        <Card title="Checklist tier changes" sub="Stocks whose research verdict moved recently. Upgrades are often worth a look first.">
          <div style={{ marginTop: 8 }}>
            {changes.slice(0, 6).map((c, i) => (<div className="kv" key={i}><span><Link to={`/stocks/${encodeURIComponent(c.symbol)}`}>{base(c.symbol)}</Link></span><span><Pill kind={tierKind(c.from ?? c.old)}>{TIER_LABEL[c.from ?? c.old] ?? "\u2014"}</Pill> to <Pill kind={tierKind(c.to ?? c.new)}>{TIER_LABEL[c.to ?? c.new] ?? "\u2014"}</Pill></span></div>))}
            {changes.length === 0 && <div className="note">{tiers.data?.computing ? "Working out tiers" : "No tier changes lately."}</div>}
          </div>
        </Card>
        <Card title="App track record" sub="Every call is written down and graded later" action={<Link to="/research/scorecard" className="btn btn--quiet">Scorecard</Link>}>
          <div style={{ marginTop: 8 }}>
            {summary.slice(0, 5).map((s, i) => (<div className="kv" key={i}><span>{CALL_KIND[s.kind] ?? s.kind}, {s.horizon_days} day{s.horizon_days === 1 ? "" : "s"}</span><span>{s.accuracy != null ? `${s.accuracy}% right of ${s.scored}` : `${s.pending} waiting`}</span></div>))}
            {summary.length === 0 && <div className="note">No calls recorded yet. Open a stock and its verdict is logged.</div>}
          </div>
        </Card>
      </div>
    </>
  );
}
