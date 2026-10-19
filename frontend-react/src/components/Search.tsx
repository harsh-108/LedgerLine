import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { base, money, pct } from "../lib/format";
import { MORE, OTHER, RESEARCH, TABS } from "../lib/nav";
import type { SymbolHit, WatchlistData } from "../lib/types";
import { Icon } from "./Icon";
import { Pill } from "./ui";

/* eslint-disable @typescript-eslint/no-explicit-any */
// Global search, as designed on the canvas: one box, results grouped into
// stocks, mutual funds, screens, pages and news. Arrow keys move, Enter opens.
interface Row { key: string; group: string; title: string; sub?: string; right?: ReactNode; go: string }
const SCREENS = [["Low debt, high ROE", "low debt quality roe"], ["Cheap and in an uptrend", "cheap value uptrend momentum"], ["Dividend payers", "dividend yield income"], ["Oversold quality", "oversold rsi dip"]];
const RECENT = "recentSearches";

function Hi({ text, q }: { text: string; q: string }) {
  const i = text.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0 || !q) return <>{text}</>;
  return <>{text.slice(0, i)}<mark>{text.slice(i, i + q.length)}</mark>{text.slice(i + q.length)}</>;
}

export function Search() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const term = q.trim();
  const low = term.toLowerCase();
  const [recent, setRecent] = useState<string[]>(() => { try { return JSON.parse(localStorage.getItem(RECENT) ?? "[]"); } catch { return []; } });

  const wl = useQuery({ queryKey: ["watchlist"], queryFn: () => api.get<WatchlistData>("/api/watchlist"), staleTime: 5 * 60_000 });
  const funds = useQuery({ queryKey: ["funds"], queryFn: () => api.get<any>("/api/funds"), staleTime: 5 * 60_000, enabled: open });
  // Server lookups wait until typing pauses: each one reaches Yahoo, and a
  // request per keystroke queued up on the phone that hosts the server.
  const [slow, setSlow] = useState(term);
  useEffect(() => { const t = setTimeout(() => setSlow(term), 300); return () => clearTimeout(t); }, [term]);
  const remote = useQuery({ queryKey: ["symbol-search", slow], queryFn: () => api.get<{ items: SymbolHit[]; error?: string | null }>(`/api/symbol-search?q=${encodeURIComponent(slow)}`), enabled: open && slow.length >= 2, staleTime: 10 * 60_000, retry: false });
  const mf = useQuery({ queryKey: ["mf-search", slow], queryFn: () => api.get<{ results: any[] }>(`/api/mf/search?q=${encodeURIComponent(slow)}`), enabled: open && slow.length >= 3, staleTime: 10 * 60_000, retry: false });
  const news = useQuery({ queryKey: ["news", "Market"], queryFn: () => api.get<{ items: any[] }>("/api/news?scope=market&limit=100"), enabled: open && term.length >= 3, staleTime: 5 * 60_000, retry: false });

  const rows: Row[] = useMemo(() => {
    if (term.length < 2) return [];
    const out: Row[] = [];
    const seen = new Set<string>();
    // the same company can be listed twice (.NS and .BO): the one with prices goes first
    const mine = [...(wl.data?.items ?? [])].sort((a, b) => Number(b.last != null) - Number(a.last != null));
    for (const i of mine) {
      if (i.type === "mf" || !i.symbol) continue;
      if (!(i.symbol.toLowerCase().includes(low) || (i.label ?? "").toLowerCase().includes(low))) continue;
      seen.add(i.symbol);
      out.push({ key: "s" + i.symbol, group: "Stocks", title: i.label || base(i.symbol), sub: `${i.symbol}, in your watchlist`, go: `/stocks/${encodeURIComponent(i.symbol)}`, right: <span className="right"><span style={{ display: "block", fontWeight: 500 }}>{money(i.last)}</span><span className={(i.pct ?? 0) >= 0 ? "gain" : "loss"} style={{ fontSize: 12.5 }}>{pct(i.pct)}</span></span> });
    }
    for (const h of remote.data?.items ?? []) { if (seen.has(h.symbol) || out.filter((r) => r.group === "Stocks").length >= 6) continue; out.push({ key: "r" + h.symbol, group: "Stocks", title: h.name || base(h.symbol), sub: `${h.symbol}${h.exch ? ", " + h.exch : ""}`, go: `/stocks/${encodeURIComponent(h.symbol)}`, right: <Pill>Not in watchlist</Pill> }); }
    // No stock hit but it looks like a ticker: offer to open it anyway, so a
    // stock is reachable (and downloadable) even when search is down.
    if (!out.some((r) => r.group === "Stocks") && /^[A-Za-z0-9&-]{2,20}(\.(ns|bo|NS|BO))?$/.test(term)) {
      const sym = term.includes(".") ? term.toUpperCase() : `${term.toUpperCase()}.NS`;
      out.push({ key: "t" + sym, group: "Stocks", title: `Open ${sym}`, sub: "Ticker typed directly", go: `/stocks/${encodeURIComponent(sym)}`, right: <Pill>Ticker</Pill> });
    }
    const tracked = new Set<number>();
    for (const f of funds.data?.funds ?? []) { if (!String(f.label).toLowerCase().includes(low)) continue; tracked.add(f.scheme_code); out.push({ key: "f" + f.scheme_code, group: "Mutual funds", title: f.label, sub: "Tracked", go: `/funds/${f.scheme_code}`, right: f.stats ? <span className="right"><span style={{ display: "block", fontWeight: 500 }}>{money(f.stats.latest_nav)}</span><span className={(f.stats.day_pct ?? 0) >= 0 ? "gain" : "loss"} style={{ fontSize: 12.5 }}>{pct(f.stats.day_pct)}</span></span> : undefined }); }
    for (const r of (mf.data?.results ?? []).slice(0, 4)) { const code = r.scheme_code ?? r.schemeCode; if (tracked.has(code)) continue; out.push({ key: "m" + code, group: "Mutual funds", title: r.name ?? r.schemeName, sub: "Not tracked yet", go: `/funds?add=${code}&name=${encodeURIComponent(r.name ?? r.schemeName ?? "")}`, right: <Pill>Track</Pill> }); }
    for (const [label, words] of SCREENS) if ((label + " " + words).toLowerCase().includes(low)) out.push({ key: "sc" + label, group: "Screens", title: label, sub: "Ready-made screen", go: `/screener?screen=${encodeURIComponent(label)}`, right: <Pill>Screen</Pill> });
    for (const n of [...TABS, ...RESEARCH, ...MORE, ...OTHER]) if (n.label.toLowerCase().includes(low) && !out.some((r) => r.go === n.to)) out.push({ key: "p" + n.to, group: "Go to", title: n.label, go: n.to });
    for (const n of (news.data?.items ?? []).filter((x) => x.title.toLowerCase().includes(low)).slice(0, 3)) out.push({ key: "n" + n.id, group: "News", title: n.title, sub: n.source, go: `/news?open=${n.id}` });
    return out;
  }, [term, low, wl.data, remote.data, funds.data, mf.data, news.data]);

  useEffect(() => setSel(0), [term]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { const tag = (e.target as HTMLElement)?.tagName; if (e.key === "/" && tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT") { e.preventDefault(); input.current?.focus(); } };
    const onDown = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    window.addEventListener("keydown", onKey); document.addEventListener("mousedown", onDown);
    return () => { window.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onDown); };
  }, []);

  const go = (r: Row) => { const next = [term, ...recent.filter((x) => x !== term)].slice(0, 5); setRecent(next); localStorage.setItem(RECENT, JSON.stringify(next)); setOpen(false); setQ(""); input.current?.blur(); navigate(r.go); };
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(rows.length - 1, s + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(0, s - 1)); }
    else if (e.key === "Enter" && rows[sel]) go(rows[sel]);
    else if (e.key === "Escape") { setOpen(false); input.current?.blur(); }
  };
  const busy = remote.isFetching || mf.isFetching || slow !== term;
  const searchErr = remote.isError ? (remote.error as Error).message : remote.data?.error;
  let lastGroup = "";

  return (<>
    {open && term.length >= 2 && <div className="scrim" style={{ zIndex: 74, background: "rgba(16,35,63,0.18)" }} />}
    <div className="search" ref={box} style={{ zIndex: open ? 76 : undefined }}>
      <Icon name="search" />
      <label htmlFor="q" className="sr-only">Search stocks, funds, screens and news</label>
      <input id="q" ref={input} type="search" autoComplete="off" role="combobox" aria-expanded={open} aria-controls="search-panel" placeholder="Search stocks, funds, screens and news" value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onKeyDown={onKeyDown} />
      {!q && <span className="kbd">/</span>}
      {open && (term.length >= 2 || recent.length > 0) && (
        <div className="search__panel" id="search-panel" role="listbox">
          {term.length >= 2 && rows.length === 0 && <div className="search__grp">{busy ? "Searching" : searchErr ? `Stock search is unavailable right now (${searchErr}). Try the exact ticker, like RELIANCE.NS.` : `Nothing matches "${term}". Try a ticker, a company name, or a fund name.`}</div>}
          {rows.map((r, i) => { const head = r.group !== lastGroup; lastGroup = r.group; return (<div key={r.key}>{head && <div className="search__grp">{r.group}</div>}<button type="button" role="option" aria-selected={i === sel} className="search__row" onMouseEnter={() => setSel(i)} onClick={() => go(r)}><span style={{ flex: 1, minWidth: 0 }}><span className="t" style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}><Hi text={r.title} q={term} /></span>{r.sub && <span className="s">{r.sub}</span>}</span>{r.right}</button></div>); })}
          <div className="search__foot">
            {recent.length > 0 && <><span>Recent</span>{recent.map((x) => <button key={x} type="button" className="pill" style={{ border: "none", cursor: "pointer" }} onClick={() => { setQ(x); input.current?.focus(); }}>{x}</button>)}</>}
            <span style={{ marginLeft: "auto" }}>Arrows to move, Enter to open, Esc to close</span>
          </div>
        </div>
      )}
    </div>
  </>);
}
