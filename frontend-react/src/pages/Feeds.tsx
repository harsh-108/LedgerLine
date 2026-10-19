import { useMemo, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { base, money } from "../lib/format";
import { MoreNav } from "../components/MoreNav";
import { Card, ErrorBox, PageHead, Pill, Seg, SkeletonCard, Stat } from "../components/ui";
import { Job } from "../components/Section";
import { usePeek } from "../components/Peek";
import { Icon } from "../components/Icon";
import { useMe } from "../lib/useMe";

/* eslint-disable @typescript-eslint/no-explicit-any */
const ago = (iso: string) => { const m = Math.max(1, Math.round((Date.now() - new Date(iso + "Z").getTime()) / 60000)); return m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };
const uniqBase = (syms: string[]) => Array.from(new Set(syms.map((s) => base(s))));

// ------------------------------------------------------------------ News
function Reader({ item, onClose }: { item: any; onClose: () => void }) {
  const qc = useQueryClient();
  const peek = usePeek();
  const explain = useMutation({ mutationFn: () => api.post<any>(`/api/news/${item.id}/explain`), meta: { quiet: true }, onSuccess: () => qc.invalidateQueries({ queryKey: ["news"] }) });
  const summary = explain.data?.summary ?? item.summary, why = explain.data?.why ?? item.why;
  return (<>
    <div className="scrim" onClick={onClose} />
    <aside className="drawer" style={{ width: "min(640px, 100vw)" }} role="dialog" aria-label="Article">
      <div className="drawer__bar"><span className="muted">{item.source}, {ago(item.published)}</span><button className="btn" style={{ height: 36 }} onClick={onClose}>Close</button></div>
      <div className="drawer__body" style={{ background: "var(--surface)" }}>
        <h2 className="display" style={{ fontSize: 26, lineHeight: 1.2 }}>{item.title}</h2>
        <div className="chips">{uniqBase(item.symbols).map((s) => <button key={s} className="chip" onClick={() => { onClose(); peek(item.symbols.find((x: string) => base(x) === s)); }}>{s}{item.held?.some((h: string) => base(h) === s) ? " (you hold this)" : ""}</button>)}</div>
        {item.excerpt && <p className="secondary" style={{ margin: 0, fontSize: 15, lineHeight: 1.65 }}>{item.excerpt}</p>}
        {summary ? (<>
          <div style={{ padding: 16, borderRadius: 12, background: "var(--ground)" }}><div className="sub" style={{ fontWeight: 600 }}>Summary</div><p style={{ margin: "6px 0 0", fontSize: 15, lineHeight: 1.65 }}>{summary}</p></div>
          {why && <div className="callout"><Icon name="bulb" /><span><b>Why it matters.</b> {why}</span></div>}
        </>) : (
          <div><button className="btn" disabled={explain.isPending} onClick={() => explain.mutate()}><Icon name="bulb" size={16} />{explain.isPending ? "Reading it" : "Explain this in plain words"}</button>{explain.isError && <p className="note loss">{(explain.error as Error).message}</p>}</div>
        )}
        <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 10 }}>
          <a className="btn btn--primary" style={{ height: 48 }} href={item.url} target="_blank" rel="noreferrer">Read the full article at {item.source || "the publisher"}</a>
          <p className="note" style={{ margin: 0 }}>The app stores the headline and the publisher's excerpt. The full text stays with the publisher and opens in a new tab.</p>
        </div>
      </div>
    </aside>
  </>);
}

export function News() {
  const [scope, setScope] = useState<"For you" | "Market">("For you");
  const [open, setOpen] = useState<any>(null);
  const news = useQuery({ queryKey: ["news", scope], queryFn: () => api.get<{ items: any[] }>(`/api/news?scope=${scope === "For you" ? "mine" : "market"}&limit=60`) });
  const items = news.data?.items ?? [];
  const [params, setParams] = useSearchParams();
  const wanted = params.get("open");
  const all = useQuery({ queryKey: ["news", "Market"], queryFn: () => api.get<{ items: any[] }>("/api/news?scope=market&limit=100"), enabled: !!wanted });
  const linked = wanted ? all.data?.items.find((i) => String(i.id) === wanted) : null;
  const [lead, ...rest] = items;
  return (
    <>
      <PageHead title="News" sub="Stories about what you own and watch come first" actions={<><Seg label="Scope" options={["For you", "Market"] as const} value={scope} onChange={setScope} /><Job label="Fetch news" start="/api/news/refresh" status="/api/news/status" /></>} />
      {news.isLoading && <SkeletonCard lines={8} />}{news.isError && <ErrorBox error={news.error} />}
      {news.data && items.length === 0 && (<Card title={scope === "For you" ? "No stories about your stocks yet" : "No stories yet"} sub="News arrives with every data refresh. You can also fetch it now with the button above."><p className="secondary" style={{ lineHeight: 1.6 }}>Sources are free RSS feeds plus a news search for each stock in your watchlist. Manage the feeds under More, Data and admin.</p></Card>)}
      {lead && (
        <Card><a href={lead.url} onClick={(e) => { e.preventDefault(); setOpen(lead); }} style={{ display: "block" }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>{lead.held?.length > 0 && <Pill kind="action">In your portfolio</Pill>}<span className="muted" style={{ fontSize: 13 }}>{lead.source}, {ago(lead.published)}</span></div>
          <h2 className="display" style={{ fontSize: 26, lineHeight: 1.2, marginTop: 10, maxWidth: "30ch" }}>{lead.title}</h2>
          {lead.excerpt && <p className="secondary" style={{ margin: "10px 0 0", fontSize: 14.5, lineHeight: 1.6, maxWidth: "70ch" }}>{lead.excerpt}</p>}
          <div className="chips" style={{ marginTop: 12 }}>{uniqBase(lead.symbols).map((s) => <span key={s} className="chip">{s}</span>)}</div>
        </a></Card>
      )}
      {rest.length > 0 && (<Card flush title="Latest">{rest.map((i) => (
        <a key={i.id} href={i.url} onClick={(e) => { e.preventDefault(); setOpen(i); }} className="story">
          <div style={{ flex: 1, minWidth: 0 }}><div className="muted" style={{ fontSize: 12.5 }}>{i.source}, {ago(i.published)}{i.held?.length > 0 && <> <Pill kind="action">You hold this</Pill></>}</div><div style={{ fontSize: 16, fontWeight: 600, lineHeight: 1.35, marginTop: 6 }}>{i.title}</div>{i.excerpt && <div className="secondary" style={{ fontSize: 13.5, marginTop: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{i.excerpt}</div>}</div>
          <div className="chips" style={{ flexShrink: 0 }}>{uniqBase(i.symbols).slice(0, 3).map((s) => <span key={s} className="chip">{s}</span>)}</div>
        </a>))}</Card>)}
      {(open || linked) && <Reader item={open ?? linked} onClose={() => { setOpen(null); if (wanted) setParams({}, { replace: true }); }} />}
    </>
  );
}

// ------------------------------------------------------------------ Calendar
const KIND: Record<string, { label: string; fg: string; bg: string }> = {
  results: { label: "Results", fg: "var(--action)", bg: "var(--action-tint)" }, dividend: { label: "Dividend", fg: "var(--gain)", bg: "var(--gain-tint)" },
  split: { label: "Split or bonus", fg: "var(--text-2)", bg: "var(--ground)" }, ipo: { label: "IPO or new fund", fg: "var(--ipo)", bg: "var(--ipo-tint)" },
};
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export function Calendar() {
  const peek = usePeek();
  const monday = (d: Date) => { const x = new Date(d); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); x.setHours(0, 0, 0, 0); return x; };
  const [start, setStart] = useState(() => monday(new Date()));
  const [only, setOnly] = useState(false);
  const [kinds, setKinds] = useState<Set<string>>(new Set(Object.keys(KIND)));
  const cal = useQuery({ queryKey: ["calendar", iso(start)], queryFn: () => api.get<{ events: any[] }>(`/api/calendar?start=${iso(start)}&days=13`) });
  const days = useMemo(() => Array.from({ length: 14 }, (_, i) => { const d = new Date(start); d.setDate(d.getDate() + i); return d; }).filter((d) => d.getDay() !== 0 && d.getDay() !== 6), [start]);
  const evs = (cal.data?.events ?? []).filter((e) => kinds.has(e.kind) && (!only || e.held));
  const shift = (n: number) => setStart((s) => { const d = new Date(s); d.setDate(d.getDate() + n); return d; });
  const today = iso(new Date());
  return (
    <>
      <PageHead title="Results calendar" sub="Results, dividends, splits and IPO dates for the next two weeks" actions={<><button className="btn" onClick={() => shift(-7)}>Previous week</button><button className="btn" onClick={() => setStart(monday(new Date()))}>This week</button><button className="btn" onClick={() => shift(7)}>Next week</button></>} />
      <MoreNav />
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        {Object.entries(KIND).map(([k, v]) => <button key={k} className="chip" style={{ height: 36, borderRadius: 999 }} aria-pressed={kinds.has(k)} onClick={() => setKinds((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; })}><span style={{ width: 10, height: 10, borderRadius: 3, background: v.fg }} />{v.label}</button>)}
        <label style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}><input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} style={{ width: 18, height: 18, accentColor: "var(--action)" }} />Only what I hold</label>
        <Job label="Update dividends and splits" start="/api/calendar/refresh" status="/api/calendar/status" />
      </div>
      {cal.isError && <ErrorBox error={cal.error} />}
      <Card flush><div className="calgrid">{days.map((d) => { const key = iso(d); const list = evs.filter((e) => e.date === key); return (
        <div key={key} className="calday"><div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 6 }}><span className="display" style={{ fontSize: 20, color: key === today ? "var(--action)" : undefined }}>{d.getDate()}</span><span className="muted" style={{ fontSize: 12.5 }}>{d.toLocaleDateString("en-IN", { weekday: "short", month: "short" })}{key === today ? ", today" : ""}</span></div>
          {list.map((e, i) => { const k = KIND[e.kind] ?? KIND.split; return (<a key={i} href="#" onClick={(ev) => { ev.preventDefault(); if (e.symbol) peek(e.symbol); }} style={{ display: "block", padding: 10, borderRadius: 10, background: k.bg, cursor: e.symbol ? "pointer" : "default" }}><span style={{ fontSize: 11.5, fontWeight: 600, color: k.fg }}>{k.label}{e.held ? ", you hold this" : ""}</span><span style={{ display: "block", fontWeight: 600, fontSize: 13.5, marginTop: 2 }}>{e.title}</span><span className="secondary" style={{ display: "block", fontSize: 12.5 }}>{e.detail}</span></a>); })}
        </div>); })}</div></Card>
      {cal.data && evs.length === 0 && <p className="note">Nothing in these two weeks. Result dates come from each stock's stored fundamentals, so they fill in after a data refresh. Dividends and splits fill in after "Update dividends and splits".</p>}
    </>
  );
}

// ------------------------------------------------------------------ IPOs
const EMPTY = { kind: "ipo", name: "", detail: "", open_date: "", close_date: "", listing_date: "", price_low: "", price_high: "", lot_size: "", issue_size: "", link: "", symbol: "", sub_total: "", sub_qib: "", sub_nii: "", sub_retail: "", gmp_pct: "", pe: "", fresh_pct: "", promoter_post: "" };
const INPUT_KEYS = ["sub_total", "sub_qib", "sub_nii", "sub_retail", "gmp_pct", "pe", "fresh_pct", "promoter_post"] as const;
const INPUT_LABEL: Record<string, string> = { sub_total: "Subscribed, total (x)", sub_qib: "QIB (x)", sub_nii: "NII (x)", sub_retail: "Retail (x)", gmp_pct: "Grey-market premium (%)", pe: "P/E at upper band", fresh_pct: "Fresh issue (%)", promoter_post: "Promoter holding after (%)" };
const VERDICT_KIND: Record<string, "gain" | "loss" | "guide" | "action" | undefined> = { both: "gain", listing: "gain", longterm: "action", ignore: "loss", mixed: "guide", unknown: undefined };

// The verdict block on an IPO card: label, one-line summary, the evidence
// for and against, and a small form to fill in what is still missing.
function IpoVerdict({ item, help }: { item: any; help: Record<string, string> }) {
  const qc = useQueryClient();
  const { isAdmin } = useMe();                // every POST under /api/ipos/ is admin-only
  const v = item.verdict;
  const [open, setOpen] = useState(false);
  const [edit, setEdit] = useState(false);
  const [f, setF] = useState<Record<string, string>>(() => Object.fromEntries([...INPUT_KEYS, "symbol"].map((k) => [k, item[k] ?? ""])));
  const [rhp, setRhp] = useState<string | null>(null);
  const inval = () => qc.invalidateQueries({ queryKey: ["ipos"] });
  const save = useMutation({ mutationFn: () => api.post(`/api/ipos/${item.id}/inputs`, f), meta: { ok: "Verdict updated" }, onSuccess: () => { setEdit(false); inval(); } });
  const pull = useMutation({ mutationFn: () => api.post<{ updated: number }>(`/api/ipos/${item.id}/subscription`), meta: { ok: (r: any) => (r?.updated ? "Subscription figures pulled from NSE" : "NSE answered, but sent no figures yet") }, onSuccess: inval, onError: inval });
  const readRhp = useMutation({ mutationFn: (url: string) => api.post<{ filled: string[]; note: string }>(`/api/ipos/${item.id}/read-rhp`, { url }), meta: { ok: (r: any) => (r?.filled?.length ? `Filled ${r.filled.length} figure${r.filled.length === 1 ? "" : "s"} from the RHP` : "Read the RHP, but found no figures") }, onSuccess: () => { setRhp(null); inval(); } });
  if (!v) return null;
  const missing: string[] = v.missing ?? [];
  const isPdf = /\.pdf(\?|$)/i.test(item.link ?? "");
  return (
    <div className="ipov">
      <div className="ipov__head">
        <span className={`pill ${VERDICT_KIND[v.tier] ? `pill--${VERDICT_KIND[v.tier]}` : ""}`} style={{ height: 28, fontSize: 13 }}>{v.label}</span>
        <button type="button" className="btn btn--quiet" style={{ height: 28, padding: "0 6px" }} aria-expanded={open} onClick={() => setOpen((o) => !o)}>{open ? "Hide why" : "Why?"}</button>
      </div>
      <p className="ipov__sum">{v.summary}</p>
      {open && (
        <div className="ipov__why">
          {v.for.length > 0 && <div><div className="ipov__h gain">For</div><ul>{v.for.map((x: any, i: number) => <li key={i}>{x.text} <span className="muted">· {x.source}</span></li>)}</ul></div>}
          {v.against.length > 0 && <div><div className="ipov__h loss">Against</div><ul>{v.against.map((x: any, i: number) => <li key={i}>{x.text} <span className="muted">· {x.source}</span></li>)}</ul></div>}
          <div className="ipov__src">
            <div className="kv"><span>Subscription</span><span className={item.sub_error ? "loss" : undefined} style={{ fontWeight: 400, textAlign: "right" }}>{item.sub_updated ? `From NSE, ${item.sub_updated}` : item.sub_error ? item.sub_error : "Not pulled yet"}</span></div>
            {item.rhp_note && <div className="kv"><span>Prospectus</span><span style={{ fontWeight: 400, textAlign: "right" }}>{item.rhp_note}</span></div>}
            {isAdmin && <div className="ipov__actions" style={{ marginTop: 8 }}>
              <button type="button" className="btn" style={{ height: 32 }} disabled={pull.isPending} onClick={() => pull.mutate()}>{pull.isPending ? "Asking NSE" : "Pull from NSE"}</button>
              <button type="button" className="btn" style={{ height: 32 }} disabled={readRhp.isPending} onClick={() => setRhp((r) => (r == null ? (isPdf ? item.link : "") : null))}>{readRhp.isPending ? "Reading" : "Read the RHP"}</button>
            </div>}
            {rhp != null && !readRhp.isPending && (
              <form onSubmit={(e) => { e.preventDefault(); if (rhp.trim()) readRhp.mutate(rhp.trim()); }} style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <input type="url" value={rhp} onChange={(e) => setRhp(e.target.value)} placeholder="Link to the RHP PDF (NSE, SEBI or the lead manager)" aria-label="RHP link" style={{ flex: 1, height: 36, padding: "0 10px", border: "1px solid var(--line)", borderRadius: 8, background: "var(--surface)", fontSize: 13 }} />
                <button className="btn btn--primary" style={{ height: 36 }} disabled={!rhp.trim()}>Read</button>
              </form>
            )}
            {readRhp.isPending && <p className="note">Downloading the prospectus and reading the offer, valuation and shareholding pages. This takes a while on a phone.</p>}
            {readRhp.isError && <ErrorBox error={readRhp.error} />}
          </div>
          {missing.length > 0 && !edit && <p className="note">Not filled in yet: {missing.map((k) => INPUT_LABEL[k]).join(", ")}.{isAdmin && <> <button type="button" className="btn btn--quiet" style={{ height: 22, padding: 0 }} onClick={() => setEdit(true)}>Add the numbers</button></>}</p>}
          {missing.length === 0 && !edit && <p className="note">All inputs filled.{isAdmin && <> <button type="button" className="btn btn--quiet" style={{ height: 22, padding: 0 }} onClick={() => setEdit(true)}>Change them</button></>}</p>}
          {edit && (
            <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="ipov__form">
              <div className="f"><label htmlFor={`${item.id}-symbol`}>NSE symbol</label><input id={`${item.id}-symbol`} value={f.symbol} placeholder="as on the exchange page" onChange={(e) => setF({ ...f, symbol: e.target.value })} /></div>
              {INPUT_KEYS.map((k) => (<div className="f" key={k} title={help[k]}><label htmlFor={`${item.id}-${k}`}>{INPUT_LABEL[k]}</label><input id={`${item.id}-${k}`} type="number" step="any" value={f[k]} placeholder={k === "pe" ? "-1 if loss-making" : ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></div>))}
              <div className="ipov__actions"><button className="btn btn--primary" disabled={save.isPending}>Save</button><button type="button" className="btn" onClick={() => setEdit(false)}>Cancel</button></div>
              <p className="note" style={{ gridColumn: "1 / -1" }}>Subscription is pulled from NSE every half hour while the issue is open, and on "Pull from NSE". P/E, fresh-issue share and promoter holding can be read from the RHP with the button above. GMP has no official source, so it stays a hand-typed mood gauge.</p>
            </form>
          )}
          <p className="note">{v.note}</p>
        </div>
      )}
    </div>
  );
}
export function Ipos() {
  const qc = useQueryClient();
  const { isAdmin } = useMe();                // add / remove / sync are admin-only
  const [kind, setKind] = useState<"IPOs" | "New fund offers">("IPOs");
  const [f, setF] = useState<Record<string, string>>(EMPTY);
  const [adding, setAdding] = useState(false);
  const list = useQuery({ queryKey: ["ipos"], queryFn: () => api.get<{ items: any[]; input_help?: Record<string, string> }>("/api/ipos") });
  const help = list.data?.input_help ?? {};
  const inval = () => { qc.invalidateQueries({ queryKey: ["ipos"] }); qc.invalidateQueries({ queryKey: ["calendar"] }); };
  const num = (v: string) => (v === "" ? null : Number(v));
  const save = useMutation({ mutationFn: () => api.post("/api/ipos", { ...f, kind: kind === "IPOs" ? "ipo" : "nfo", price_low: num(f.price_low), price_high: num(f.price_high), lot_size: num(f.lot_size), detail: f.detail || null, open_date: f.open_date || null, close_date: f.close_date || null, listing_date: f.listing_date || null, issue_size: f.issue_size || null, link: f.link || null, symbol: f.symbol || null, ...Object.fromEntries(INPUT_KEYS.map((k) => [k, num(f[k])])) }), meta: { ok: () => `${f.name} saved` }, onSuccess: () => { setF(EMPTY); setAdding(false); inval(); } });
  const del = useMutation({ mutationFn: (id: number) => api.del(`/api/ipos/${id}`), meta: { ok: "Removed" }, onSuccess: inval });
  const sync = useMutation({ mutationFn: () => api.post<any>("/api/ipos/sync"), meta: { ok: (r: any) => `NSE sync: ${r?.added_or_updated ?? 0} issues added or updated` }, onSuccess: inval });
  const items = (list.data?.items ?? []).filter((i) => (kind === "IPOs" ? i.kind === "ipo" : i.kind === "nfo"));
  const by = (s: string) => items.filter((i) => i.status === s);
  const inp = (k: string, label: string, type = "text", ph = "") => (<div className="f"><label htmlFor={`ipo-${k}`}>{label}</label><input id={`ipo-${k}`} type={type} value={f[k]} placeholder={ph} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></div>);
  const band = (i: any) => (i.price_low && i.price_high && i.price_low !== i.price_high ? `${money(i.price_low, 0)} to ${money(i.price_high, 0)}` : i.price_high ? money(i.price_high, 0) : "To be announced");
  const onSubmit = (e: FormEvent) => { e.preventDefault(); if (f.name.trim()) save.mutate(); };
  const verdictPill = (i: any) => (i.verdict ? <Pill kind={VERDICT_KIND[i.verdict.tier]}>{i.verdict.label}</Pill> : <span className="muted">\u2014</span>);
  const table = (rows: any[], empty: string) => (<div className="table-wrap"><table className="table"><thead><tr><th>Name</th><th>Opens</th><th>Closes</th><th>Lists</th><th className="right">Price</th>{kind === "IPOs" && <th>Verdict</th>}<th>Source</th><th /></tr></thead><tbody>
    {rows.map((i) => (<tr key={i.id}><td className="name">{i.link ? <a href={i.link} target="_blank" rel="noreferrer">{i.name}</a> : i.name}<small>{i.detail}</small></td><td>{i.open_date ?? "\u2014"}</td><td>{i.close_date ?? "\u2014"}</td><td>{i.listing_date ?? "\u2014"}</td><td className="right">{band(i)}</td>{kind === "IPOs" && <td title={i.verdict?.summary}>{verdictPill(i)}</td>}<td><Pill>{i.source === "nse" ? "NSE" : "Added by hand"}</Pill></td><td className="right">{isAdmin && <button className="btn btn--quiet" aria-label={`Remove ${i.name}`} onClick={() => del.mutate(i.id)}><Icon name="x" size={15} /></button>}</td></tr>))}
    {rows.length === 0 && <tr><td colSpan={8} className="muted">{empty}</td></tr>}</tbody></table></div>);
  return (
    <>
      <PageHead title="IPOs and new funds" sub="Companies and funds opening to investors for the first time" actions={<><Seg label="Kind" options={["IPOs", "New fund offers"] as const} value={kind} onChange={setKind} />{isAdmin && <><button className="btn" disabled={sync.isPending} onClick={() => sync.mutate()}><Icon name="refresh" size={16} />{sync.isPending ? "Asking NSE" : "Fill from NSE"}</button><button className="btn btn--primary" onClick={() => setAdding((a) => !a)}><Icon name="plus" size={16} />Add one</button></>}</>} />
      <MoreNav />
      {adding && (<Card title={kind === "IPOs" ? "Add an IPO" : "Add a new fund offer"} sub="Only the name is required. Dates can be typed as 2026-09-22 or 22-Sep-2026.">
        <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
          <div className="form-row">{inp("name", kind === "IPOs" ? "Company" : "Fund name")}{inp("detail", kind === "IPOs" ? "What it does" : "Category")}</div>
          <div className="form-row">{inp("open_date", "Opens", "date")}{inp("close_date", "Closes", "date")}{inp("listing_date", kind === "IPOs" ? "Lists on" : "Reopens on", "date")}</div>
          {kind === "IPOs" && <div className="form-row">{inp("price_low", "Price band, low", "number")}{inp("price_high", "Price band, high", "number")}{inp("lot_size", "Lot size", "number")}{inp("issue_size", "Issue size", "text", "1,200 Cr")}</div>}
          {inp("link", kind === "IPOs" ? "Link to the prospectus or exchange page" : "Link to the AMFI scheme document", "url")}
          {kind === "IPOs" && (<details className="ipov__more"><summary>Verdict inputs, optional — subscription, GMP, valuation</summary>
            <div className="form-row" style={{ marginTop: 8 }}>{inp("symbol", "NSE symbol", "text", "as on the exchange page")}{inp("sub_total", INPUT_LABEL.sub_total, "number")}{inp("sub_qib", INPUT_LABEL.sub_qib, "number")}{inp("sub_nii", INPUT_LABEL.sub_nii, "number")}{inp("sub_retail", INPUT_LABEL.sub_retail, "number")}</div>
            <div className="form-row">{inp("gmp_pct", INPUT_LABEL.gmp_pct, "number")}{inp("pe", INPUT_LABEL.pe, "number", "-1 if loss-making")}{inp("fresh_pct", INPUT_LABEL.fresh_pct, "number")}{inp("promoter_post", INPUT_LABEL.promoter_post, "number")}</div>
          </details>)}
          <div><button className="btn btn--primary" disabled={save.isPending || !f.name.trim()}>Save</button></div>
        </form></Card>)}
      {list.isError && <ErrorBox error={list.error} />}
      <h2 style={{ fontSize: 17 }}>Open now</h2>
      {by("open").length === 0 ? <p className="note" style={{ margin: 0 }}>Nothing is open right now.</p> : (
        <div className="grid grid-3" style={{ alignItems: "start" }}>{by("open").map((i) => (<Card key={i.id}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}><div><div className="display" style={{ fontSize: 18 }}>{i.name}</div><div className="muted" style={{ fontSize: 13 }}>{i.detail}</div></div><Pill kind="guide">{i.days_left === 0 ? "Closes today" : `Closes in ${i.days_left} day${i.days_left === 1 ? "" : "s"}`}</Pill></div>
          <div className="grid grid-2" style={{ marginTop: 14 }}><Stat label="Price band" value={band(i)} /><Stat label="Open dates" value={`${i.open_date} to ${i.close_date}`} />{i.lot_size ? <Stat label="Lot size" value={`${i.lot_size} shares`} /> : null}{i.min_investment ? <Stat label="Minimum investment" value={money(i.min_investment, 0)} /> : null}</div>
          {i.verdict && <IpoVerdict item={i} help={help} />}
          {i.link && <a className="btn" style={{ marginTop: 14 }} href={i.link} target="_blank" rel="noreferrer">Read the details</a>}
        </Card>))}</div>)}
      <Card flush title="Coming soon">{table(by("upcoming"), "Nothing upcoming has been added.")}</Card>
      <Card flush title="Recently closed or listed">{table([...by("closed"), ...by("listed")], "Nothing here yet.")}</Card>
      <div className="callout"><Icon name="bulb" /><span><b>New to IPOs?</b> An IPO is a company selling shares to the public for the first time. You apply for a lot, and may get all, some, or none of it. Listing-day gains are not guaranteed. <Link to="/more/learn" style={{ textDecoration: "underline" }}>Learn more</Link></span></div>
      <p className="note">There is no free official feed for IPOs. "Fill from NSE" reads NSE's public pages through nsepython and fails at times; while an issue is open it also pulls the subscription figures. Anything you add by hand always stays. The verdict is the app's reading of the numbers entered — listing gains from demand and market mood, long term from valuation and where the money goes — never a recommendation.</p>
    </>
  );
}

// ------------------------------------------------------------------ Feed manager (used in Data and admin)
export function FeedManager() {
  const qc = useQueryClient();
  const [x, setX] = useState({ name: "", url: "" });
  const feeds = useQuery({ queryKey: ["feeds"], queryFn: () => api.get<{ feeds: any[] }>("/api/news/feeds") });
  const inval = () => qc.invalidateQueries({ queryKey: ["feeds"] });
  const add = useMutation({ mutationFn: () => api.post("/api/news/feeds", x), meta: { ok: "Feed added" }, onSuccess: () => { setX({ name: "", url: "" }); inval(); } });
  const del = useMutation({ mutationFn: (id: number) => api.del(`/api/news/feeds/${id}`), meta: { ok: "Feed removed" }, onSuccess: inval });
  return (
    <Card title="News feeds" sub="Any RSS or Atom address. Each stock in your watchlist also gets its own news search.">
      <div style={{ marginTop: 8 }}>{(feeds.data?.feeds ?? []).map((fd) => <div className="kv" key={fd.id}><span title={fd.url}>{fd.name}</span><button className="btn btn--quiet" style={{ height: 24, padding: 0 }} onClick={() => del.mutate(fd.id)}>Remove</button></div>)}</div>
      <form onSubmit={(e) => { e.preventDefault(); if (x.url) add.mutate(); }} style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 12 }}>
        <div className="f"><label htmlFor="fn">Name</label><input id="fn" value={x.name} onChange={(e) => setX({ ...x, name: e.target.value })} placeholder="Publisher, markets" /></div>
        <div className="f"><label htmlFor="fu">Feed address</label><input id="fu" type="url" value={x.url} onChange={(e) => setX({ ...x, url: e.target.value })} placeholder="https://..." /></div>
        <div style={{ display: "flex", gap: 8 }}><button className="btn" disabled={!x.url || add.isPending}>Add feed</button><Job label="Fetch news" start="/api/news/refresh" status="/api/news/status" /></div>
      </form>
    </Card>
  );
}

// News about one stock, for the Research tab.
export function StockNews({ symbol }: { symbol: string }) {
  const q = useQuery({ queryKey: ["news", "symbol", symbol], queryFn: () => api.get<{ items: any[] }>(`/api/news?symbol=${encodeURIComponent(symbol)}&limit=6`), retry: false });
  return (
    <Card title="In the news" sub="Headlines that mention this stock">
      <div style={{ marginTop: 8 }}>
        {(q.data?.items ?? []).map((i) => <a key={i.id} className="kv" href={i.url} target="_blank" rel="noreferrer" style={{ alignItems: "flex-start", padding: "8px 0" }}><span style={{ color: "var(--ink)", fontWeight: 500, lineHeight: 1.4 }}>{i.title}</span><span className="muted" style={{ flexShrink: 0, fontWeight: 400 }}>{ago(i.published)}</span></a>)}
        {q.data && q.data.items.length === 0 && <div className="note">Nothing stored yet. News arrives with each data refresh.</div>}
        {q.isError && <div className="note">Not available yet. {(q.error as Error).message}</div>}
      </div>
      <Link className="btn" to="/news" style={{ marginTop: 10 }}>All news</Link>
    </Card>
  );
}
