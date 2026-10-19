import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import INFO from "../lib/info.json";
import { useSettings } from "../lib/settings";

// The "i" buttons from the previous app: every technical term explained in
// plain words. The text lives in lib/info.json (ported from ui-fx.js).
type Entry = { t: string; d: string };
const DICT = INFO as Record<string, Entry>;
const ALIAS: Record<string, string> = {
  "P/E ratio": "P/E", "P/B ratio": "P/B", ROE: "ROE %", "ROE %": "ROE %", "Debt to equity": "D/E", "Dividend yield": "Div yield %", "Div yield %": "Div yield %",
  "Median %": "Median", "Positive %": "Positive", "Best %": "Best", "Worst %": "Worst", "RSI (14)": "RSI", "RSI 14": "RSI",
  "Strategy CAGR": "CAGR %", "Max fall": "Max fall %", "Research verdict": "__verdict", "Position size": "__sizer", "Research checklist": "Checklist verdict",
  "Chance of closing up tomorrow": "P(up tomorrow)", "Win rate": "Win rate", "What happened historically": "Any period (baseline)", Momentum: "Momentum z", Value: "Value z", Quality: "Quality z", Trend: "Trend z",
  "What the rule says now": "Rule today", "Cost per side, %": "Cost per side", "Track for": "Tracking period", "Tracking": "Tracking period", "Against NIFTYBEES": "Against NIFTYBEES", "Rule says now": "Rule today",
};
export const infoKey = (label: string): string | null => { const k = ALIAS[label] ?? label; return DICT[k] ? k : null; };

const W = 320, GAP = 8, EDGE = 16;

export function InfoTip({ k }: { k: string }) {
  const key = infoKey(k);
  const { tips } = useSettings();
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number; up: boolean } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLSpanElement>(null);

  // The popup is portalled to <body> with fixed coordinates, so it is never
  // clipped by a scrolling table and never pushes the page wider than the
  // window. It flips above the button when there is no room below.
  const place = () => {
    const b = btn.current?.getBoundingClientRect();
    if (!b) return;
    const vw = document.documentElement.clientWidth, vh = window.innerHeight;
    const w = Math.min(W, vw - 2 * EDGE);
    const left = Math.max(EDGE, Math.min(b.left - 12, vw - w - EDGE));
    const h = pop.current?.offsetHeight ?? 0;
    const up = h > 0 && b.bottom + GAP + h > vh - EDGE && b.top - GAP - h > EDGE;
    setPos({ left, top: up ? b.top - GAP - h : b.bottom + GAP, up });
  };
  useLayoutEffect(() => { if (open) place(); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent) {
        // close only the tip: without stopPropagation the same Escape also
        // reached the stock drawer's window listener and shut the drawer
        if (e.key === "Escape") { e.stopPropagation(); setOpen(false); }
        return;
      }
      const t = e.target as Node;
      if (!btn.current?.contains(t) && !pop.current?.contains(t)) setOpen(false);
    };
    // Follow the button while anything scrolls; close only once it has left
    // the screen. Closing on every scroll event made tips inside the drawer
    // and scrolling tables vanish the instant they opened, since focusing a
    // half-visible button scrolls it into view.
    const follow = () => {
      const b = btn.current?.getBoundingClientRect();
      if (!b || b.bottom < 0 || b.top > window.innerHeight) setOpen(false);
      else place();
    };
    document.addEventListener("mousedown", close); document.addEventListener("keydown", close);
    window.addEventListener("scroll", follow, true); window.addEventListener("resize", follow);
    return () => {
      document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close);
      window.removeEventListener("scroll", follow, true); window.removeEventListener("resize", follow);
    };
  }, [open]);
  if (!key || !tips) return null;
  const e = DICT[key];
  return (
    <span className="info">
      <button ref={btn} type="button" className="info__btn" aria-label={`What is ${e.t}?`} aria-expanded={open} onClick={(ev) => { ev.preventDefault(); ev.stopPropagation(); setOpen((o) => !o); }}>i</button>
      {open && createPortal(
        <span ref={pop} className="info__pop" role="tooltip" style={{ position: "fixed", left: pos?.left ?? -9999, top: pos?.top ?? 0, width: Math.min(W, document.documentElement.clientWidth - 2 * EDGE), visibility: pos ? "visible" : "hidden" }}>
          <b>{e.t}</b>{e.d.split("\n\n").map((p, i) => <span key={i}>{p}</span>)}
        </span>,
        document.body,
      )}
    </span>
  );
}

// Label plus its "i", when the term is known.
export function Term({ children }: { children: string }): ReactNode {
  return <>{children}{infoKey(children) && <InfoTip k={children} />}</>;
}
