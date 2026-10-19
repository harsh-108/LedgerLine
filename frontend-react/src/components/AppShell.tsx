import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BRAND } from "../lib/brand";
import { api } from "../lib/api";
import { money, pct } from "../lib/format";
import { TABS } from "../lib/nav";
import type { Me, RefreshStatus, TapeItem } from "../lib/types";
import { Icon, Logo } from "./Icon";
import { ErrorBoundary } from "./ErrorBoundary";
import { PeekProvider, usePeek } from "./Peek";
import { Toaster, toast } from "./Toast";
import { Confirmer } from "./Confirm";
import { Search } from "./Search";
import { useSettings } from "../lib/settings";
import { MORE, RESEARCH } from "../lib/nav";
import { visibleNav } from "../lib/useMe";

function Ribbon() {
  const peek = usePeek();
  const [paused, setPaused] = useState(false);
  const qc = useQueryClient();
  const tape = useQuery({ queryKey: ["tape"], queryFn: () => api.get<{ items: TapeItem[] }>("/api/tape"), refetchInterval: 60_000 });
  const status = useQuery({
    queryKey: ["refresh-status"],
    queryFn: () => api.get<RefreshStatus>("/api/refresh/status"),
    refetchInterval: (q) => (q.state.data?.running ? 2000 : false),
  });
  const refresh = useMutation({
    mutationFn: () => api.post("/api/refresh"),
    meta: { ok: "Refreshing data. This can take a few minutes." },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["refresh-status"] }),
  });

  // When a refresh finishes, reload everything on screen.
  const wasRunning = useRef(false);
  useEffect(() => {
    const running = !!status.data?.running;
    if (wasRunning.current && !running) { qc.invalidateQueries(); toast("Data refresh finished"); }
    wasRunning.current = running;
  }, [status.data?.running, qc]);

  const prefs = useSettings();
  const items = (tape.data?.items ?? []).filter((t) => (prefs.ribbonShows === "held" ? t.held : prefs.ribbonShows === "watch" ? !t.held : true));
  const speed = prefs.ribbonSpeed; // seconds each item takes to cross
  const group = (hidden: boolean) => (
    <div className="ribbon__group" aria-hidden={hidden || undefined}>
      {items.map((t) => (
        <a key={t.symbol} href={`/stocks/${encodeURIComponent(t.symbol)}`} onClick={(e) => { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); peek(t.symbol); }} className="ribbon__item" tabIndex={hidden ? -1 : undefined} title={t.held ? "In your portfolio" : undefined}>
          <b>{t.label}</b>
          <span className="px">{money(t.last)}</span>
          {t.pct != null && <span className={t.pct >= 0 ? "up" : "down"}>{pct(t.pct)}</span>}
        </a>
      ))}
    </div>
  );

  return (
    <div className="ribbon">
      <Link to="/watchlists" className="ribbon__label"><Icon name="star" size={14} />{prefs.ribbonShows === "held" ? "Your holdings" : prefs.ribbonShows === "watch" ? "Your watchlist" : "Your stocks"}</Link>
      <div className="ribbon__window">
        {items.length > 0 && (
          <div className="ribbon__track" data-paused={paused} style={{ animationDuration: `${Math.max(40, items.length * speed)}s` }}>{group(false)}{group(true)}</div>
        )}
      </div>
      <div className="ribbon__side">
        <span>{status.data?.running ? "Refreshing data" : "Prices as of last refresh"}</span>
        <button className="ribbon__btn" aria-label="Refresh data" disabled={status.data?.running || refresh.isPending} onClick={() => refresh.mutate()}>
          <Icon name="refresh" size={13} />
        </button>
        <button className="ribbon__btn" aria-label={paused ? "Play ticker" : "Pause ticker"} onClick={() => setPaused((p) => !p)}>
          <Icon name={paused ? "play" : "pause"} size={13} />
        </button>
      </div>
    </div>
  );
}

export function AppShell() {
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/auth/me") });
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const logout = useMutation({
    mutationFn: () => api.post("/api/auth/logout"),
    onSuccess: () => { qc.clear(); navigate("/login"); },
  });
  const initials = (me.data?.user ?? "").slice(0, 2).toUpperCase() || "ME";
  const isActive = (to: string) => (to === "/" ? pathname === "/" : pathname.startsWith("/" + to.split("/")[1]));

  const prefs = useSettings();
  const actions = (
    <div className="bar__actions">
      <Link to="/alerts" className="icon-btn bell" aria-label="Alerts"><Icon name="bell" size={19} /></Link>
      <Link to="/settings" className="icon-btn gear" aria-label="Settings"><Icon name="gear" size={19} /></Link>
      <button className="avatar" title={`Signed in as ${me.data?.user ?? ""}. Click to sign out.`} aria-label="Sign out" onClick={() => logout.mutate()}>{initials}</button>
    </div>
  );
  const side = prefs.nav === "side";
  const sideLink = (to: string, label: string) => <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>{label}</NavLink>;

  return (
    <PeekProvider>
    <div className={`app ${side ? "app--side" : ""}`}>
      {prefs.ribbon && <div className="ribbonwrap"><Ribbon /></div>}
      {side ? (
        <nav className="side" aria-label="Main">
          <Link to="/" className="brand"><Logo /><span>{BRAND.name}</span></Link>
          {TABS.filter((t) => !["Research", "More"].includes(t.label)).map((t) => sideLink(t.to, t.label))}
          <div className="grp">Research</div>{RESEARCH.map((t) => sideLink(t.to, t.label))}
          <div className="grp">More</div>{visibleNav(MORE, me.data?.role === "admin").map((t) => sideLink(t.to, t.label))}
        </nav>
      ) : null}
      <div className={side ? "col" : "app__col"} style={side ? undefined : { display: "contents" }}>
      <header>
        <div className="bar">
          {!side && <Link to="/" className="brand"><Logo /><span>{BRAND.name}</span></Link>}
          <Search />
          {actions}
        </div>
        {!side && (
          <nav className="tabs" aria-label="Main">
            {TABS.map((t) => (<NavLink key={t.to} to={t.to} className={() => (isActive(t.to) ? "active" : "")}>{t.label}</NavLink>))}
            <Link to="/more/learn" className="learn"><Icon name="book" size={15} />&nbsp;Learn as you go</Link>
          </nav>
        )}
      </header>
      <main className="main"><ErrorBoundary resetKey={pathname}><Outlet /></ErrorBoundary></main>
      <footer className="footer">
        <span>Buy and sell calls are the app's reading of stored, possibly delayed data.</span>
        <span>Not investment advice.</span>
      </footer>
      </div>
      <Toaster />
      <Confirmer />
    </div>
    </PeekProvider>
  );
}
