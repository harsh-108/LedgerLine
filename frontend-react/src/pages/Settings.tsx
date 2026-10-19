import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Me } from "../lib/types";
import { setSettings, useSettings, type Settings as S } from "../lib/settings";
import { Card, PageHead } from "../components/ui";

// The left list is a set of tabs: one section shows at a time, and the
// chosen one lives in the URL hash (/settings#account) so links and the
// back button keep working.
const SECTIONS = [["experience", "Experience"], ["appearance", "Appearance"], ["data", "Data and display"], ["notifications", "Notifications"], ["account", "Account"]] as const;
type SectionId = (typeof SECTIONS)[number][0];
const isSection = (v: string): v is SectionId => SECTIONS.some(([id]) => id === v);

function Row({ label, detail, children }: { label: string; detail?: string; children: ReactNode }) {
  return <div className="setrow"><div><div className="l">{label}</div>{detail && <div className="d">{detail}</div>}</div>{children}</div>;
}
function Switch({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return <button type="button" role="switch" aria-checked={on} aria-label={label} className="switch" onClick={() => onChange(!on)}><span /></button>;
}
function Opt({ on, onClick, title, detail, children }: { on: boolean; onClick: () => void; title: ReactNode; detail?: string; children?: ReactNode }) {
  return <button type="button" className="opt" aria-pressed={on} onClick={onClick}>{children}<b>{title}</b>{detail && <small>{detail}</small>}</button>;
}
const Swatch = ({ bg, bar, line }: { bg: string; bar: string; line: string }) => (<div className="swatch" style={{ background: bg }}><i style={{ width: "60%", background: bar }} /><i style={{ width: "85%", background: line }} /><i style={{ width: "40%", background: line }} /></div>);

export default function Settings() {
  const s = useSettings();
  const qc = useQueryClient();
  const set = <K extends keyof S>(k: K, v: S[K]) => setSettings({ [k]: v } as Partial<S>);
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/auth/me") });
  const isAdmin = me.data?.role === "admin";
  const logout = useMutation({ mutationFn: () => api.post("/api/auth/logout"), onSuccess: () => { qc.clear(); window.location.href = "/login"; } });
  const tg = useQuery({ queryKey: ["telegram"], queryFn: () => api.get<{ configured: boolean; bot: string | null; linked: boolean; tg_username: string | null }>("/api/telegram/status") });
  const tgLink = useMutation({ mutationFn: () => api.post<{ url: string; expires_min: number }>("/api/telegram/link-code"), onSuccess: (d) => window.open(d.url, "_blank", "noopener") });
  const tgUnlink = useMutation({ mutationFn: () => api.del("/api/telegram/link"), meta: { ok: "Telegram disconnected" }, onSuccess: () => { tg.refetch(); qc.invalidateQueries({ queryKey: ["me"] }); } });
  const sendMine = useMutation({ mutationFn: () => api.post("/api/digest/send-mine"), meta: { ok: "Digest sent to your Telegram" } });
  const [pw, setPw] = useState({ cur: "", next: "" });
  const changePw = useMutation({ mutationFn: () => api.post("/api/auth/change-password", { current_password: pw.cur, new_password: pw.next }), meta: { ok: "Password changed. Other devices were signed out." }, onSuccess: () => { setPw({ cur: "", next: "" }); qc.invalidateQueries({ queryKey: ["me"] }); } });
  const logoutOthers = useMutation({ mutationFn: () => api.post<{ ended: number }>("/api/auth/logout-others"), meta: { ok: (r: any) => r?.ended ? `Signed out of ${r.ended} other ${r.ended === 1 ? "device" : "devices"}` : "No other devices were signed in" }, onSuccess: () => qc.invalidateQueries({ queryKey: ["me"] }) });
  const others = Math.max(0, (me.data?.sessions ?? 1) - 1);
  const pick = (id: string, value: string, options: [string, string][], onChange: (v: string) => void) => (<select id={id} value={value} onChange={(e) => onChange(e.target.value)} aria-label={id}>{options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>);

  const { hash } = useLocation();
  const navigate = useNavigate();
  const fromHash = hash.replace(/^#/, "");
  const active: SectionId = isSection(fromHash) ? fromHash : "experience";
  const show = (id: SectionId) => navigate({ hash: id }, { replace: true });
  useEffect(() => { window.scrollTo({ top: 0 }); }, [active]);

  return (
    <>
      <PageHead title="Settings" sub="Changes save automatically, in this browser" />
      <div className="settings">
        <nav className="card settings__nav" role="tablist" aria-label="Settings sections">
          {SECTIONS.map(([id, l]) => <button key={id} type="button" role="tab" id={`tab-${id}`} aria-selected={active === id} aria-controls={`panel-${id}`} onClick={() => show(id)}>{l}</button>)}
        </nav>
        <div className="settings__panel" role="tabpanel" id={`panel-${active}`} aria-labelledby={`tab-${active}`}>
          {active === "experience" && <Card title="Explanations" sub="How much help you see next to the numbers"><div style={{ marginTop: 12 }}>
              <Row label="Explain numbers in plain language" detail="Shows readings like Low debt next to ratios on stock pages"><Switch on={s.explain} onChange={(v) => set("explain", v)} label="Explain numbers in plain language" /></Row>
              <Row label="Show learning tips" detail="The small i buttons that explain each term"><Switch on={s.tips} onChange={(v) => set("tips", v)} label="Show learning tips" /></Row>
              <Row label="Open charts as candlesticks" detail="Off shows a simple line first"><Switch on={s.candles} onChange={(v) => set("candles", v)} label="Open charts as candlesticks" /></Row>
            </div></Card>}

          {active === "appearance" && <Card title="Appearance">
              <div className="subhead">Theme</div>
              <div className="opts">
                <Opt on={s.theme === "light"} onClick={() => set("theme", "light")} title="Light"><Swatch bg="#FFFFFF" bar="#2456E6" line="#DCE3EC" /></Opt>
                <Opt on={s.theme === "dark"} onClick={() => set("theme", "dark")} title="Dark"><Swatch bg="#10233F" bar="#8FA8FF" line="#2A4268" /></Opt>
                <Opt on={s.theme === "device"} onClick={() => set("theme", "device")} title="Match device"><Swatch bg="#EDF1F5" bar="#2456E6" line="#B9C6DA" /></Opt>
              </div>
              <div className="subhead">Navigation</div>
              <div className="opts">
                <Opt on={s.nav === "top"} onClick={() => set("nav", "top")} title="Top bar" detail="More room for tables and charts." />
                <Opt on={s.nav === "side"} onClick={() => set("nav", "side")} title="Left sidebar" detail="Keeps every section one click away." />
              </div>
              <div className="subhead">Gain and loss colors</div>
              <div className="opts">
                <Opt on={s.updown === "green-up"} onClick={() => set("updown", "green-up")} title={<><span style={{ color: "#0A7D4F" }}>Green up</span>, <span style={{ color: "#C9302C" }}>red down</span></>} />
                <Opt on={s.updown === "red-up"} onClick={() => set("updown", "red-up")} title={<><span style={{ color: "#C9302C" }}>Red up</span>, <span style={{ color: "#0A7D4F" }}>green down</span></>} />
              </div>
              <div style={{ marginTop: 18 }}>
                <Row label="Watchlist ribbon" detail="Scrolling prices at the top of every page"><Switch on={s.ribbon} onChange={(v) => set("ribbon", v)} label="Watchlist ribbon" /></Row>
                <Row label="Ribbon shows">{pick("ribbonShows", s.ribbonShows, [["all", "Holdings, then watchlist"], ["held", "My holdings only"], ["watch", "Watchlist only"]], (v) => set("ribbonShows", v as S["ribbonShows"]))}</Row>
                <Row label="Ribbon speed">{pick("ribbonSpeed", String(s.ribbonSpeed), [["9", "Slow"], ["6", "Normal"], ["4", "Fast"]], (v) => set("ribbonSpeed", Number(v) as S["ribbonSpeed"]))}</Row>
                <Row label="Table density">{pick("density", s.density, [["comfortable", "Comfortable"], ["compact", "Compact"]], (v) => set("density", v as S["density"]))}</Row>
              </div>
            </Card>}

          {active === "data" && <Card title="Data and display"><div style={{ marginTop: 12 }}>
              <Row label="Currency" detail="Prices come from Indian exchanges"><span className="secondary">Indian rupee</span></Row>
              <Row label="Large numbers">{pick("numbers", s.numbers, [["indian", "Lakh and crore"], ["international", "Million and billion"]], (v) => set("numbers", v as S["numbers"]))}</Row>
              <Row label="Default chart range">{pick("range", s.range, [["1M", "1 month"], ["6M", "6 months"], ["1Y", "1 year"], ["5Y", "5 years"], ["Max", "All history"]], (v) => set("range", v as S["range"]))}</Row>
              <Row label="Default chart type">{pick("charttype", s.candles ? "c" : "l", [["c", "Candlestick"], ["l", "Line"]], (v) => set("candles", v === "c"))}</Row>
              <Row label="Dates and times" detail="Shown as stored by the exchange, in Indian time"><span className="secondary">Set from the data</span></Row>
            </div></Card>}

          {active === "notifications" && <Card title="Notifications"><div style={{ marginTop: 12 }}>
              <Row label="Confirmations" detail="A short message when something is added, saved or removed. Errors always show."><Switch on={s.confirmations} onChange={(v) => set("confirmations", v)} label="Confirmations" /></Row>
              <Row label="Price alerts" detail="Checked after every data refresh. Each fires once, then switches off."><Link className="btn" to="/alerts">Manage</Link></Row>
              <Row label="Telegram" detail={tg.data?.linked ? `Connected${tg.data.tg_username ? ` as @${tg.data.tg_username}` : ""}. Alerts and the Sunday digest go there.` : tg.data?.configured === false ? "The server has no Telegram bot configured" : "Get your alerts and the weekly digest in a Telegram chat"}>
                {tg.data?.linked ? <div style={{ display: "flex", gap: 8 }}><button className="btn" disabled={sendMine.isPending} onClick={() => sendMine.mutate()}>Send digest now</button><button className="btn" onClick={() => tgUnlink.mutate()}>Disconnect</button></div> : <button className="btn btn--primary" disabled={!tg.data?.configured || tgLink.isPending} onClick={() => tgLink.mutate()}>Connect Telegram</button>}
              </Row>
              {tgLink.isSuccess && !tg.data?.linked && <p className="note">A Telegram window opened. Press <b>Start</b> in it, then <button className="btn btn--quiet" onClick={() => { tg.refetch(); qc.invalidateQueries({ queryKey: ["me"] }); }}>check again</button>. The link expires in {tgLink.data.expires_min} minutes.</p>}
            </div></Card>}

          {active === "account" && <Card title="Account"><div style={{ marginTop: 12 }}>
              <Row label="Signed in as" detail={me.data?.email ? `${me.data.email}${me.data.has_google ? " · Google linked" : ""}` : "No email on this account"}><b>{me.data?.user ?? ""}{isAdmin ? " (admin)" : ""}</b></Row>
              <Row label="AI analyst" detail={me.data?.analyst?.limit == null ? "Unlimited questions" : "Questions reset at midnight"}><span className="secondary">{me.data?.analyst?.limit == null ? `${me.data?.analyst?.used ?? 0} used today` : `${me.data.analyst.used} of ${me.data.analyst.limit} used today`}</span></Row>
              <Row label="Change password" detail="Signs out your other devices">
                <form onSubmit={(e) => { e.preventDefault(); if (pw.cur && pw.next.length >= 8) changePw.mutate(); }} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <input type="password" autoComplete="current-password" placeholder="Current" value={pw.cur} onChange={(e) => setPw({ ...pw, cur: e.target.value })} aria-label="Current password" style={{ width: 120 }} />
                  <input type="password" autoComplete="new-password" placeholder="New, 8+ chars" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} aria-label="New password" style={{ width: 130 }} />
                  <button className="btn" disabled={changePw.isPending || !pw.cur || pw.next.length < 8}>Change</button>
                </form>
              </Row>
              <Row label="Other devices" detail={`${others === 0 ? "Only this browser is signed in" : `${others} other ${others === 1 ? "browser or device is" : "browsers or devices are"} signed in`}. Lost a phone or used a shared computer? Sign them out.${me.data?.telegram_linked ? " New sign-ins are announced on your Telegram." : " Link Telegram under Notifications to hear about every new sign-in."}`}>
                <button className="btn" disabled={logoutOthers.isPending || others === 0} onClick={() => logoutOthers.mutate()}>Sign out other devices</button>
              </Row>
              {isAdmin && <Row label="Users and invites" detail="Invite people, manage roles, run data jobs"><Link className="btn" to="/more/admin">Data and admin</Link></Row>}
              <Row label="Sign out" detail="On this browser"><button className="btn" onClick={() => logout.mutate()}>Sign out</button></Row>
            </div></Card>}
        </div>
      </div>
      <p className="note">Charts use TradingView Lightweight Charts, copyright TradingView, Inc. <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer" style={{ textDecoration: "underline" }}>tradingview.com</a></p>
    </>
  );
}
