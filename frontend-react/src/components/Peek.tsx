import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { base } from "../lib/format";
import { StockView } from "./StockView";

// Quick look: clicking a stock in the ribbon, Home or a watchlist opens it in
// a side panel, so you keep your place. The full page is one click away.
const Ctx = createContext<(symbol: string) => void>(() => {});
export const usePeek = () => useContext(Ctx);

export function PeekProvider({ children }: { children: ReactNode }) {
  const [symbol, setSymbol] = useState<string | null>(null);
  const { pathname } = useLocation();
  useEffect(() => setSymbol(null), [pathname]);
  useEffect(() => {
    if (!symbol) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setSymbol(null);
    window.addEventListener("keydown", onKey); document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [symbol]);
  return (
    <Ctx.Provider value={setSymbol}>
      {children}
      {symbol && (<>
        <div className="scrim" onClick={() => setSymbol(null)} />
        <aside className="drawer" role="dialog" aria-label={`${base(symbol)} quick look`}>
          <div className="drawer__bar">
            <b>{base(symbol)}</b>
            <div style={{ display: "flex", gap: 8 }}>
              <Link className="btn btn--primary" style={{ height: 36 }} to={`/stocks/${encodeURIComponent(symbol)}`}>Open full page</Link>
              <button className="btn" style={{ height: 36 }} onClick={() => setSymbol(null)}>Close</button>
            </div>
          </div>
          <div className="drawer__body compact"><StockView raw={symbol} compact /></div>
        </aside>
      </>)}
    </Ctx.Provider>
  );
}

// A link-looking button that opens the quick look.
export function PeekLink({ symbol, children }: { symbol: string; children: ReactNode }) {
  const peek = usePeek();
  return <a href={`/stocks/${encodeURIComponent(symbol)}`} onClick={(e) => { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); peek(symbol); }}>{children}</a>;
}
