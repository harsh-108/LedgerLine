import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { base, compact, money } from "../lib/format";
import { signalLabel } from "../lib/labels";
import type { WatchItem, WatchlistData } from "../lib/types";
import { Card, Change, ErrorBox, PageHead, Pill, Seg, SkeletonCard, Sparkline } from "../components/ui";
import { Icon } from "../components/Icon";
import { usePeek } from "../components/Peek";
import { StockPicker, type PickerHit } from "../components/StockPicker";

/* eslint-disable @typescript-eslint/no-explicit-any */
const TYPES = ["Stock", "ETF", "Mutual fund"] as const;
const TYPE_KEY: Record<(typeof TYPES)[number], string> = { Stock: "stock", ETF: "etf", "Mutual fund": "mf" };

export default function Watchlists() {
  const qc = useQueryClient();
  const peek = usePeek();
  const [q, setQ] = useState("");
  const [type, setType] = useState<(typeof TYPES)[number]>("Stock");
  const [tag, setTag] = useState("all");
  const [editing, setEditing] = useState<number | null>(null);
  const dragId = useRef<number | null>(null);

  const list = useQuery({ queryKey: ["watchlist"], queryFn: () => api.get<WatchlistData>("/api/watchlist") });
  const changed = useQuery({ queryKey: ["changed"], queryFn: () => api.get<{ since: string | null; signals: any[] }>("/api/changed"), staleTime: Infinity });
  const isFund = type === "Mutual fund";
  const fundSearch = (term: string) => api.get<{ results: any[] }>(`/api/mf/search?q=${encodeURIComponent(term)}`).then((r) => r.results.map((x): PickerHit => ({ symbol: String(x.scheme_code ?? x.schemeCode), name: x.name ?? x.schemeName, right: "Fund", bare: true })));
  const inval = () => { ["watchlist", "tape", "home", "funds"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })); };

  const add = useMutation({
    mutationFn: (h: { key: string; name: string }) => (isFund ? api.post("/api/mf/add", { scheme_code: Number(h.key), label: h.name }) : api.post<any>("/api/watchlist/add", { symbol: h.key, asset_type: TYPE_KEY[type] })),
    meta: { ok: (_r: unknown, h: any) => `${h.name || base(h.key)} added to your watchlist` }, onSuccess: () => { setQ(""); inval(); },
  });
  const remove = useMutation({ mutationFn: (i: WatchItem) => api.del(`/api/watchlist/${i.id}`), meta: { ok: (_r: unknown, i: any) => `${i.label || base(i.symbol)} removed` }, onSuccess: inval });
  const setTagM = useMutation({ mutationFn: (v: { id: number; tag: string }) => api.post(`/api/watchlist/${v.id}/tag`, { tag: v.tag }), meta: { ok: "Tag saved" }, onSuccess: () => { setEditing(null); inval(); } });
  const reorder = useMutation({ mutationFn: (ids: number[]) => api.post("/api/watchlist/reorder", { ids }), meta: { ok: "Order saved" }, onSuccess: inval });
  const download = useMutation({ mutationFn: (i: WatchItem) => api.post<any>(`/api/download/${encodeURIComponent(i.symbol)}`), meta: { ok: (r: any, i: any) => `Downloaded ${r?.rows ?? ""} days for ${i.label || base(i.symbol)}` }, onSuccess: inval });

  const items = list.data?.items ?? [];
  const tags = useMemo(() => ["all", ...Array.from(new Set(items.map((i) => i.tag).filter(Boolean) as string[]))], [items]);
  const shown = tag === "all" ? items : items.filter((i) => i.tag === tag);
  const up = items.filter((i) => (i.pct ?? 0) > 0).length, down = items.filter((i) => (i.pct ?? 0) < 0).length;
  const drop = (targetId: number) => { const from = dragId.current; dragId.current = null; if (from == null || from === targetId) return; const ids = items.map((i) => i.id); const a = ids.indexOf(from), b = ids.indexOf(targetId); ids.splice(b, 0, ids.splice(a, 1)[0]); reorder.mutate(ids); };
  const signals = changed.data?.signals ?? [];

  return (
    <>
      <PageHead title="Watchlists" sub="Keep an eye on stocks and funds without buying them"
        actions={<div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <Seg label="Type" options={TYPES} value={type} onChange={(t) => { setType(t); setQ(""); }} />
          <div style={{ width: 320 }}>
            <StockPicker key={type} id="add" label="Add to watchlist" hideLabel value={q} onChange={setQ} disabled={add.isPending}
              placeholder={isFund ? "Fund name, 3 or more letters" : "Add a company or ticker"}
              mine={false} {...(isFund ? { search: fundSearch, searchKey: "funds", minChars: 3 } : {})}
              onPick={(h) => add.mutate({ key: h.symbol, name: h.name })} />
          </div>
        </div>} />
      {add.isPending && <div className="note">Adding, and downloading its price history. This can take a moment.</div>}

      {signals.length > 0 && (
        <Card title="What changed since your last visit" sub={changed.data?.since ? `Since ${changed.data.since}` : undefined}>
          <div style={{ marginTop: 8 }}>{signals.slice(0, 6).map((s, i) => (<div className="kv" key={i}><span><a href="#" onClick={(e) => { e.preventDefault(); peek(s.symbol); }}><Pill kind="action">{base(s.symbol)}</Pill></a> {signalLabel(s.signal)}</span><span className="muted">{money(s.price)}</span></div>))}</div>
        </Card>
      )}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
        <div className="chips">{tags.map((t) => <button key={t} type="button" className="chip" aria-pressed={t === tag} onClick={() => setTag(t)}>{t}</button>)}</div>
        <span className="secondary"><b className="gain">{up} up</b> and <b className="loss">{down} down</b> today. <Link to="/alerts" style={{ textDecoration: "underline" }}>Alerts</Link></span>
      </div>

      {list.isLoading && <SkeletonCard lines={8} />}
      {list.isError && <ErrorBox error={list.error} />}
      {list.data && items.length === 0 && (<Card><div style={{ textAlign: "center", padding: "48px 16px" }}><h2 style={{ fontSize: 24 }}>Start your first watchlist</h2><p className="secondary" style={{ maxWidth: "52ch", margin: "8px auto 0", lineHeight: 1.6 }}>A watchlist lets you follow prices for stocks and funds without buying them. It also feeds the ribbon at the top of every page. Type a ticker in the box above.</p></div></Card>)}
      {shown.length > 0 && (
        <Card flush>
          <div className="table-wrap"><table className="table">
            <thead><tr><th style={{ width: 28 }} /><th>Name</th><th className="right">Price / NAV</th><th className="right">Today</th><th className="right">Market cap</th><th className="right">Recent</th><th>Tag</th><th /></tr></thead>
            <tbody>
              {shown.map((i) => (
                <tr key={i.id} draggable={tag === "all"} onDragStart={() => { dragId.current = i.id; }} onDragOver={(e) => e.preventDefault()} onDrop={() => drop(i.id)}>
                  <td className="drag" title="Drag to reorder">::</td>
                  <td className="name">
                    {i.type === "mf" ? <Link to={`/funds/${i.scheme_code}`}>{i.label}</Link> : <a href={`/stocks/${encodeURIComponent(i.symbol)}`} onClick={(e) => { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); peek(i.symbol); }}>{i.label || base(i.symbol)}</a>}
                    {i.type !== "stock" && <> <Pill kind="action">{i.type === "mf" ? "Fund" : "ETF"}</Pill></>}
                    <small>{i.type === "mf" ? "Mutual fund" : i.symbol}</small>
                  </td>
                  <td className="right">{i.last != null ? money(i.last) : i.type !== "mf" ? <button className="btn" style={{ height: 30 }} disabled={download.isPending} onClick={() => download.mutate(i)}>Download history</button> : "\u2014"}</td>
                  <td className="right"><Change value={i.pct} /></td>
                  <td className="right">{compact(i.mcap)}</td>
                  <td className="right"><Sparkline values={i.spark} /></td>
                  <td>{editing === i.id ? (
                    <form onSubmit={(e) => { e.preventDefault(); const v = (e.currentTarget.elements.namedItem("tag") as HTMLInputElement).value.trim(); setTagM.mutate({ id: i.id, tag: v }); }}><input name="tag" autoFocus defaultValue={i.tag ?? ""} onBlur={() => setEditing(null)} placeholder="tag" aria-label={`Tag for ${i.label || i.symbol}`} style={{ width: 110, height: 30, padding: "0 8px", border: "1px solid var(--action)", borderRadius: 8, background: "var(--surface)" }} /></form>
                  ) : (<button type="button" className="pill" style={{ border: "none", cursor: "pointer" }} onClick={() => setEditing(i.id)}>{i.tag || "+ tag"}</button>)}</td>
                  <td className="right"><button className="btn btn--quiet" onClick={() => remove.mutate(i)} aria-label={`Remove ${i.label || i.symbol}`}><Icon name="x" size={15} /></button></td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </Card>
      )}
      <p className="note">Click a name for a quick look. Drag the handle to reorder. Click a tag to edit it.</p>
    </>
  );
}
