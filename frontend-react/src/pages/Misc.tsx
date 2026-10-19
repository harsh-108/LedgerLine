import { useMemo, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { getDetail } from "../lib/detail";
import { base, compact, money } from "../lib/format";
import { PORTFOLIO } from "../lib/nav";
import { MoreNav } from "../components/MoreNav";
import { useMe } from "../lib/useMe";
import { useWatchSymbols } from "../lib/symbols";
import { Card, ErrorBox, PageHead, Pill, Seg, Stat } from "../components/ui";
import { RecordsTable } from "../components/RecordsTable";
import { SeriesChart } from "../components/SeriesChart";
import { Job, SubNav, SymbolSelect } from "../components/Section";
import { FeedManager } from "./Feeds";
import { confirmDialog } from "../components/Confirm";
import { DataDoctor } from "../components/DataDoctor";
import { CATS, GUIDES, TERMS, type Cat } from "../lib/learn";

/* eslint-disable @typescript-eslint/no-explicit-any */

// ---------------------------------------------------------------- Alerts
export function Alerts() {
  const qc = useQueryClient();
  const symbols = useWatchSymbols();
  const [params] = useSearchParams();
  const [sym, setSym] = useState(params.get("symbol") ?? "");
  const [kind, setKind] = useState("price_above");
  const [value, setValue] = useState("");
  const a = useQuery({ queryKey: ["alerts"], queryFn: () => api.get<{ kinds: Record<string, string>; alerts: any[] }>("/api/alerts") });
  const add = useMutation({ mutationFn: () => api.post("/api/alerts", { symbol: sym, kind, value: Number(value) || 0 }), meta: { ok: "Alert created" }, onSuccess: () => { setValue(""); qc.invalidateQueries({ queryKey: ["alerts"] }); } });
  const del = useMutation({ mutationFn: (id: number) => api.del(`/api/alerts/${id}`), meta: { ok: "Alert removed" }, onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }) });
  const kinds = a.data?.kinds ?? {};
  const describe = (x: any) => (kinds[x.kind] ?? x.kind).replace("VALUE", String(x.value));
  const onSubmit = (e: FormEvent) => { e.preventDefault(); if (sym) add.mutate(); };
  return (
    <>
      <PageHead title="Alerts" sub="Get told when something you care about happens, so you do not have to keep checking" />
      <div className="row" style={{ alignItems: "flex-start" }}>
        <Card flush className="grow-2" title="Active alerts">
          <div className="table-wrap"><table className="table"><thead><tr><th>Stock</th><th>Alert me when</th><th /></tr></thead>
            <tbody>{(a.data?.alerts ?? []).map((x) => (<tr key={x.id}><td className="name"><Link to={`/stocks/${encodeURIComponent(x.symbol)}`}>{base(x.symbol)}</Link></td><td className="secondary">{describe(x)}</td><td className="right"><button className="btn btn--quiet" onClick={() => del.mutate(x.id)}>Remove</button></td></tr>))}
              {(a.data?.alerts ?? []).length === 0 && <tr><td colSpan={3} className="muted">No alerts yet.</td></tr>}</tbody></table></div>
        </Card>
        <Card className="grow" title="New alert">
          <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 12 }}>
            <SymbolSelect id="als" value={sym} onChange={setSym} symbols={symbols} />
            <div className="f"><label htmlFor="alk">Alert me when</label><select id="alk" value={kind} onChange={(e) => setKind(e.target.value)}>{Object.entries(kinds).map(([k, v]) => <option key={k} value={k}>{v.replace("VALUE", "a level")}</option>)}</select></div>
            <div className="f"><label htmlFor="alv">Level</label><input id="alv" type="number" step="any" value={value} onChange={(e) => setValue(e.target.value)} /></div>
            {add.isError && <ErrorBox error={add.error} />}
            <button className="btn btn--primary" disabled={!sym || add.isPending}>Create alert</button>
          </form>
        </Card>
      </div>
      <p className="note">Alerts are checked after every data refresh. Each one fires once, to the app and to Telegram if connected, then switches itself off until you add it again.</p>
    </>
  );
}

// ---------------------------------------------------------------- Compare
const COLORS = ["--action", "--teal", "#E0664F", "#7C4DDB"];
export function Compare() {
  const symbols = useWatchSymbols();
  const [params] = useSearchParams();
  const [picked, setPicked] = useState<string[]>(params.get("s") ? [params.get("s")!] : []);
  const [next, setNext] = useState("");
  const details = useQuery({ queryKey: ["compare", picked], queryFn: () => Promise.all(picked.map((s) => getDetail(s))), enabled: picked.length > 0 });
  const series = useMemo(() => (details.data ?? []).map((d, i) => { const c = d.candles.slice(-252); const b = c[0]?.close || 1; return { name: base(d.symbol), color: COLORS[i], data: c.map((x: any) => ({ time: x.time, value: +((x.close / b - 1) * 100).toFixed(2) })) }; }), [details.data]);
  const F: [string, string, (v: number) => string, "hi" | "lo" | null][] = [["Market cap", "marketCap", (v) => compact(v), null], ["P/E ratio", "trailingPE", (v) => v.toFixed(1), "lo"], ["P/B ratio", "priceToBook", (v) => v.toFixed(1), "lo"], ["ROE", "returnOnEquity", (v) => (v * 100).toFixed(1) + "%", "hi"], ["Debt to equity", "debtToEquity", (v) => (v / 100).toFixed(2), "lo"], ["Net margin", "profitMargins", (v) => (v * 100).toFixed(1) + "%", "hi"]];
  return (
    <>
      <PageHead title="Compare" sub="Line up to four stocks side by side" />
      <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
        {picked.map((s, i) => <span key={s} className="pill" style={{ height: 40, fontSize: 14, background: "var(--surface)", border: "1px solid var(--line)", gap: 8 }}><span style={{ width: 10, height: 10, borderRadius: "50%", background: COLORS[i].startsWith("--") ? `var(${COLORS[i]})` : COLORS[i] }} />{base(s)}<button className="btn btn--quiet" style={{ height: 24, padding: 0 }} aria-label={`Remove ${s}`} onClick={() => setPicked(picked.filter((x) => x !== s))}>x</button></span>)}
        {picked.length < 4 && <><div style={{ width: 200 }}><SymbolSelect id="cmp" value={next} onChange={setNext} symbols={symbols.filter((s) => !picked.includes(s))} label="Add a stock" /></div><button className="btn" disabled={!next} onClick={() => { setPicked([...picked, next]); setNext(""); }}>Add</button></>}
      </div>
      {details.isError && <ErrorBox error={details.error} />}
      {series.length > 0 && <Card title="Return over the past year, %"><div style={{ marginTop: 12 }}><SeriesChart series={series} height={280} /></div></Card>}
      {details.data && details.data.length > 0 && (
        <Card flush><div className="table-wrap"><table className="table"><thead><tr><th />{details.data.map((d) => <th key={d.symbol} className="right">{base(d.symbol)}</th>)}</tr></thead>
          <tbody>{F.map(([label, key, fmt, best]) => { const vals = details.data!.map((d) => (typeof d.fundamentals?.[key] === "number" ? d.fundamentals[key] : null)); const ok = vals.filter((v) => v != null) as number[]; const target = best === "hi" ? Math.max(...ok) : best === "lo" ? Math.min(...ok) : null; return (<tr key={key}><td className="secondary">{label}</td>{vals.map((v, i) => <td key={i} className="right">{v == null ? "\u2014" : v === target && ok.length > 1 ? <Pill kind="gain">{fmt(v)}</Pill> : fmt(v)}</td>)}</tr>); })}
            <tr><td className="secondary">Checklist</td>{details.data.map((d) => <td key={d.symbol} className="right">{d.checklist ? `${d.checklist.passed} of ${d.checklist.applicable}` : "\u2014"}</td>)}</tr></tbody></table></div></Card>
      )}
    </>
  );
}

// ---------------------------------------------------------------- Reports
export function Reports() {
  const tax = useQuery({ queryKey: ["tax"], queryFn: () => api.get<{ years: any[] }>("/api/taxreport") });
  const p = useQuery({ queryKey: ["portfolio"], queryFn: () => api.get<any>("/api/portfolio") });
  return (
    <>
      <PageHead title="Reports" sub="Gains, dividends, and statements. Tax owed depends on your situation, so share these with your tax adviser." /><SubNav items={PORTFOLIO} />
      {tax.isError && <ErrorBox error={tax.error} />}
      {(tax.data?.years ?? []).map((y: any, i: number) => (<Card flush key={i} title={`Financial year ${y.fy ?? ""}`} sub="Short term is held under 12 months, long term is over"><RecordsTable rows={[Object.fromEntries(Object.entries(y).filter(([, v]) => typeof v !== "object"))]} symbolKey="" />{Array.isArray(y.sales ?? y.rows) && <RecordsTable rows={y.sales ?? y.rows} symbolKey="symbol" />}</Card>))}
      {tax.data && tax.data.years.length === 0 && <Card title="No sales recorded yet"><p className="secondary">When you record a sale in Portfolio tools, the gain lands here, split into short and long term by the 1-year rule.</p><Link className="btn" to="/portfolio/tools">Open Portfolio tools</Link></Card>}
      <Card flush title="Dividends received"><RecordsTable rows={(p.data?.dividends ?? []).map((d: any) => ({ Stock: base(d.symbol), Date: d.date, Amount: d.amount, Note: d.note ?? "" }))} symbolKey="" empty="None recorded." /></Card>
    </>
  );
}

// ---------------------------------------------------------------- Calculators
export function Calculators() {
  const [mode, setMode] = useState<"Monthly SIP" | "One-time">("Monthly SIP");
  const [amt, setAmt] = useState(10000), [years, setYears] = useState(15), [rate, setRate] = useState(12);
  const data = useMemo(() => { const i = rate / 100 / 12; const out = []; for (let y = 0; y <= years; y++) { const n = y * 12; const value = mode === "Monthly SIP" ? (i ? amt * ((Math.pow(1 + i, n) - 1) / i) * (1 + i) : amt * n) : amt * Math.pow(1 + rate / 100, y); out.push({ y, value, invested: mode === "Monthly SIP" ? amt * n : amt }); } return out; }, [amt, years, rate, mode]);
  const last = data[data.length - 1];
  const yr = new Date().getFullYear();
  const slider = (id: string, label: string, v: number, set: (n: number) => void, min: number, max: number, step: number, show: string) => (<div style={{ padding: "14px 0", borderTop: "1px solid var(--line)" }}><div style={{ display: "flex", justifyContent: "space-between" }}><label htmlFor={id} style={{ fontWeight: 500 }}>{label}</label><b>{show}</b></div><input id={id} type="range" min={min} max={max} step={step} value={v} onChange={(e) => set(Number(e.target.value))} style={{ width: "100%", accentColor: "var(--action)", marginTop: 10 }} /></div>);
  return (
    <>
      <PageHead title="Calculators" sub="Estimates only. Markets do not grow in a straight line." /><MoreNav />
      <div className="row">
        <Card className="grow" title="What could my investment grow to?" action={<Seg label="Mode" options={["Monthly SIP", "One-time"] as const} value={mode} onChange={setMode} />}>
          <div style={{ marginTop: 14 }}>{slider("ca", mode === "Monthly SIP" ? "Monthly amount" : "Amount", amt, setAmt, 500, 100000, 500, money(amt, 0))}{slider("cy", "For how many years", years, setYears, 1, 40, 1, `${years} years`)}{slider("cr", "Expected yearly return", rate, setRate, 1, 20, 0.5, `${rate}%`)}</div>
          <p className="note">Not sure what return to expect? Try a lower number too.</p>
        </Card>
        <Card className="grow-2">
          <div style={{ display: "flex", gap: 32, flexWrap: "wrap" }}><Stat label="You invest" value={money(last.invested, 0)} /><Stat label="Estimated gains" value={<span className="gain">{money(last.value - last.invested, 0)}</span>} /><Stat big label={`Estimated value after ${years} years`} value={money(last.value, 0)} /></div>
          <div style={{ marginTop: 14 }}><SeriesChart series={[{ name: "Estimated value", color: "--action", data: data.map((d) => ({ time: `${yr + d.y}-01-01`, value: Math.round(d.value) })) }, { name: "Amount invested", color: "--slate", dashed: true, data: data.map((d) => ({ time: `${yr + d.y}-01-01`, value: d.invested })) }]} /></div>
        </Card>
      </div>
      <p className="note">Position sizing lives in <Link to="/portfolio/tools" style={{ textDecoration: "underline" }}>Portfolio tools</Link>.</p>
    </>
  );
}

// ---------------------------------------------------------------- Learn
export function Learn() {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState<"All" | Cat>("All");
  const [open, setOpen] = useState<string | null>(null);
  const low = q.trim().toLowerCase();
  const guides = GUIDES.filter((g) => !low || (g.title + g.summary + g.body.join(" ")).toLowerCase().includes(low));
  const terms = TERMS.filter((t) => (cat === "All" || t.cat === cat) && (!low || (t.term + " " + t.def).toLowerCase().includes(low))).sort((a, b) => a.term.localeCompare(b.term));
  const g = GUIDES.find((x) => x.id === open);
  return (
    <>
      <PageHead title="Learn" sub={`${GUIDES.length} short guides and ${TERMS.length} terms, in plain words`} actions={<input aria-label="Search guides and terms" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search, like NAV or backtest" style={{ height: 40, width: 260, padding: "0 12px", border: "1px solid var(--line)", borderRadius: 10, background: "var(--surface)" }} />} /><MoreNav />
      {g ? (
        <Card title={g.title} sub={`${g.minutes} min read`} action={<button className="btn" onClick={() => setOpen(null)}>All guides</button>}>
          <div className="guide">{g.body.map((p, i) => <p key={i}>{p}</p>)}</div>
          {g.link && <Link className="btn btn--primary" to={g.link.to} style={{ marginTop: 6 }}>{g.link.label}</Link>}
        </Card>
      ) : guides.length > 0 && (
        <section>
          <h2 className="section-title">Guides</h2>
          <div className="guide-grid">{guides.map((x) => (
            <button key={x.id} type="button" className="card guide-card" onClick={() => { setOpen(x.id); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
              <span className="muted" style={{ fontSize: 12.5 }}>{x.minutes} min read</span>
              <b>{x.title}</b>
              <span className="secondary">{x.summary}</span>
            </button>
          ))}</div>
        </section>
      )}
      <Card title="Glossary" sub={`${terms.length} of ${TERMS.length} terms`} action={<Seg label="Topic" options={["All", ...CATS] as const} value={cat} onChange={setCat} />}>
        <div className="grid grid-2" style={{ columnGap: 40, rowGap: 0, marginTop: 8 }}>{terms.map((t) => (<div key={t.term} style={{ padding: "14px 0", borderTop: "1px solid var(--line)" }}><div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "baseline" }}><span style={{ fontWeight: 600, fontSize: 15 }}>{t.term}</span>{cat === "All" && <span className="muted" style={{ fontSize: 12 }}>{t.cat}</span>}</div><div className="secondary" style={{ fontSize: 13.5, marginTop: 3, lineHeight: 1.5 }}>{t.def}</div></div>))}</div>
        {terms.length === 0 && <p className="note">No term matches "{q}"{cat !== "All" ? ` in ${cat}` : ""}.</p>}
      </Card>
    </>
  );
}

// ---------------------------------------------------------------- Data and admin
export function Admin() {
  const [u, setU] = useState({ username: "", password: "" });
  const unis = useQuery({ queryKey: ["universes"], queryFn: () => api.get<{ universes: any[] }>("/api/universes") });
  const nse = useQuery({ queryKey: ["nse"], queryFn: () => api.get<any>("/api/nse/status"), retry: false });
  const ai = useQuery({ queryKey: ["analyst-status"], queryFn: () => api.get<any>("/api/analyst/status"), retry: false });
  const digest = useMutation({ mutationFn: () => api.get<{ text: string; telegram_configured: boolean; last_sent: string | null }>("/api/digest") });
  const sendDigest = useMutation({ mutationFn: () => api.post<{ ok: boolean; sent_at: string }>("/api/digest/send"), meta: { ok: "Digest sent to Telegram" } });
  const addUser = useMutation({ mutationFn: () => api.post("/api/auth/add-user", u), meta: { ok: () => `Account "${u.username.trim().toLowerCase()}" created` }, onSuccess: () => { setU({ username: "", password: "" }); users.refetch(); } });
  const { me, isAdmin, isLoading: meLoading } = useMe();
  const qc = useQueryClient();
  const invites = useQuery({ queryKey: ["invites"], queryFn: () => api.get<{ invites: any[]; signup_url: string }>("/api/admin/invites"), enabled: isAdmin });
  const users = useQuery({ queryKey: ["users"], queryFn: () => api.get<{ users: any[] }>("/api/admin/users"), enabled: isAdmin });
  const mkInvite = useMutation({ mutationFn: (n: number) => api.post<{ code: string; url: string }>("/api/admin/invites", { max_uses: n }), meta: { ok: "Invite created" }, onSuccess: () => qc.invalidateQueries({ queryKey: ["invites"] }) });
  const rmInvite = useMutation({ mutationFn: (code: string) => api.del(`/api/admin/invites/${code}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["invites"] }) });
  const setRole = useMutation({ mutationFn: (x: { u: string; role: string }) => api.post(`/api/admin/users/${x.u}/role`, { role: x.role }), meta: { ok: "Role updated" }, onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }) });
  const confirmUser = useMutation({ mutationFn: (u: string) => api.post(`/api/admin/users/${u}/confirm`), meta: { ok: "Email marked as confirmed; they can log in now" }, onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }) });
  const delUser = useMutation({ mutationFn: (u: string) => api.del(`/api/admin/users/${u}`), meta: { ok: (_r: unknown, u: any) => `${u} deleted, along with their watchlist, portfolio and alerts` }, onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }) });
  const authCfg = useQuery({ queryKey: ["auth-status"], queryFn: () => api.get<{ invite_required?: boolean; google_invite_required?: boolean }>("/api/auth/status") });
  if (!meLoading && !isAdmin) return (<><PageHead title="Data and admin" sub="Admin only" /><MoreNav /><Card title="Admin only"><p className="secondary">This page is for the account that runs the app. Your own settings are under the gear icon.</p></Card></>);
  return (
    <>
      <PageHead title="Data and admin" sub="Where the numbers come from, and who can use the app" /><MoreNav />
      <DataDoctor />
      <div className="admin">
        <Card title="Data refresh" sub="Prices, fundamentals, NAVs, then signals and alerts"><div style={{ marginTop: 12 }}><Job primary label="Refresh data" start="/api/refresh" status="/api/refresh/status" /></div></Card>
        <Card title="NSE sync" sub="Delivery data and exchange prices">{nse.data && !nse.data.available ? <p className="note">Not installed. Run: pip install nsepython, then restart the backend.</p> : <div style={{ marginTop: 12 }}><Job label="Run NSE sync" start="/api/nse/sync" status="/api/nse/status" /></div>}</Card>
        <Card title="Screener universes"><div style={{ marginTop: 8 }}>{(unis.data?.universes ?? []).map((x) => <div className="kv" key={x.name}><span>{x.name}</span><span>{x.missing === 0 ? <Pill kind="gain">Ready</Pill> : <Pill kind="guide">{x.with_prices} of {x.total}</Pill>}</span></div>)}</div><p className="note">Download missing data from the Screener page.</p></Card>
        <Card title="AI provider chain" sub="Used by the analyst and the plain-English screener"><div style={{ marginTop: 8 }}>{(ai.data?.providers ?? []).map((p: any, i: number) => <div className="kv" key={i}><span>{i + 1}. {typeof p === "string" ? p : p.name}</span><span>{typeof p === "object" ? p.status ?? "" : ""}</span></div>)}{(ai.data?.providers ?? []).length === 0 && <p className="note">No keys set. Add OPENROUTER_API_KEY or GROQ_API_KEY to .env.</p>}</div></Card>
        <Card title="Weekly digest" sub="Preview it here; sending goes to Telegram every Sunday 18:00, or now with the button">
          <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
            <button className="btn" disabled={digest.isPending} onClick={() => digest.mutate()}>Preview</button>
            <button className="btn btn--primary" disabled={sendDigest.isPending || digest.data?.telegram_configured === false} onClick={() => sendDigest.mutate()}>Send to Telegram now</button>
          </div>
          {digest.data?.telegram_configured === false && <p className="note">Telegram isn't configured: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env and restart.</p>}
          {(sendDigest.data?.sent_at || digest.data?.last_sent) && <p className="note">Last sent {sendDigest.data?.sent_at ?? digest.data?.last_sent}</p>}
          {digest.data && <pre className="log" style={{ maxHeight: 260 }}>{digest.data.text}</pre>}
          {digest.isError && <ErrorBox error={digest.error} />}{sendDigest.isError && <ErrorBox error={sendDigest.error} />}
        </Card>
        <FeedManager />
        <Card title="Invite people" sub={authCfg.data?.invite_required === false ? "Sign-up is open: no code needed" : authCfg.data?.google_invite_required ? "Each code lets someone sign up with their email, or with Google" : "Each code lets someone sign up with email and password. Google sign-up needs no code."}>
          <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
            <button className="btn btn--primary" disabled={mkInvite.isPending} onClick={() => mkInvite.mutate(1)}>New single-use code</button>
            <button className="btn" disabled={mkInvite.isPending} onClick={() => mkInvite.mutate(10)}>Code for 10 people</button>
          </div>
          {mkInvite.data && <p className="note">Share this link: <code style={{ userSelect: "all" }}>{mkInvite.data.url}</code></p>}
          <div style={{ marginTop: 10 }}>{(invites.data?.invites ?? []).map((i) => <div className="kv" key={i.code}><span><code>{i.code}</code> {i.note ? `· ${i.note}` : ""}</span><span>{i.uses}/{i.max_uses} used {i.exhausted ? "" : <button className="btn btn--quiet" onClick={() => rmInvite.mutate(i.code)}>Revoke</button>}</span></div>)}{invites.data && invites.data.invites.length === 0 && <p className="note">No invite codes yet.</p>}</div>
        </Card>
        <Card title="Users" sub="Who has an account, and who can run data jobs">
          <div style={{ marginTop: 8 }}>{(users.data?.users ?? []).map((x) => <div className="kv" key={x.username}><span><b>{x.username}</b> <span className="secondary">{x.email ?? "no email"}{x.email && !x.email_verified ? " · unconfirmed" : ""}{x.telegram ? ` · @${x.telegram}` : ""}</span></span><span>{x.role}{" "}{x.email && !x.email_verified && <button className="btn btn--quiet" disabled={confirmUser.isPending} onClick={() => confirmUser.mutate(x.username)}>Confirm</button>}{" "}<button className="btn btn--quiet" onClick={() => setRole.mutate({ u: x.username, role: x.role === "admin" ? "user" : "admin" })}>{x.role === "admin" ? "Make user" : "Make admin"}</button>{x.username !== me?.user && <>{" "}<button className="btn btn--quiet loss" disabled={delUser.isPending} onClick={async () => { if (await confirmDialog({ title: `Delete ${x.username}?`, body: <>Their watchlist, portfolio, alerts, notes and sign-ins go with the account. <b>This cannot be undone.</b></>, confirmLabel: "Delete account", cancelLabel: "Keep", danger: true })) delUser.mutate(x.username); }}>Delete</button></>}</span></div>)}</div>
          {delUser.isError && <ErrorBox error={delUser.error} />}
          <p className="note">Deleting removes the account and all its data. You cannot delete yourself or the last admin.</p>
        </Card>
        <Card title="Add a user without email" sub="For family on the LAN. They can add an email later in Settings.">
          <form onSubmit={(e) => { e.preventDefault(); addUser.mutate(); }} style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
            <div className="f"><label htmlFor="nu">Username</label><input id="nu" value={u.username} onChange={(e) => setU({ ...u, username: e.target.value })} required /></div>
            <div className="f"><label htmlFor="np">Password, 8 or more characters</label><input id="np" type="password" value={u.password} onChange={(e) => setU({ ...u, password: e.target.value })} required minLength={8} /></div>
            {addUser.isError && <ErrorBox error={addUser.error} />}{addUser.isSuccess && <div className="note gain">User created.</div>}
            <button className="btn btn--primary" disabled={addUser.isPending}>Add user</button>
          </form>
        </Card>
      </div>
      <p className="note">Forgot a password? On the machine running the app: python scripts/reset_password.py. Prices come from Yahoo Finance, with NSE and SmartAPI as fallbacks, and fund NAVs from AMFI.</p>
    </>
  );
}
