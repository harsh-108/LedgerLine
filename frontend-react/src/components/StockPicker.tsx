import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { base, exchange } from "../lib/format";
import type { SymbolHit, WatchlistData } from "../lib/types";

// Type a company name or ticker, pick from the list: the form gets the full
// exchange symbol (LICI.NS) without the user ever typing a suffix.
//  - default: your watchlist matches first, then NSE/BSE listings from
//    /api/symbol-search. Typing without picking still passes the raw text up;
//    the backend resolves it.
//  - options: pick only from a fixed list (e.g. your holdings when selling).
//    The list opens on focus, typing filters it, and only a pick counts.
//    Names are looked up too, so "south indian" finds SOUTHBANK.NS.
//  - search: a custom remote search (e.g. mutual funds on the watchlist page).
export interface PickerHit { symbol: string; name: string; right?: string; bare?: boolean }
const symbolSearch = (term: string) => api.get<{ items: SymbolHit[] }>(`/api/symbol-search?q=${encodeURIComponent(term)}`).then((r) => r.items.map((h): PickerHit => ({ symbol: h.symbol, name: h.name, right: h.exch })));

export function StockPicker({ id, label, value, onChange, onPick, options, search = symbolSearch, searchKey = "stocks", minChars = 2, mine = true, nameSearch = true, hideLabel, disabled, required, placeholder = "Company name or ticker" }: {
  id: string; label: string; value: string; onChange: (symbol: string) => void;
  onPick?: (h: PickerHit) => void; options?: PickerHit[];
  search?: (term: string) => Promise<PickerHit[]>; searchKey?: string; minChars?: number; mine?: boolean; nameSearch?: boolean;
  hideLabel?: boolean; disabled?: boolean; required?: boolean; placeholder?: string;
}) {
  const strict = !!options;
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<PickerHit | null>(null);
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState(0);
  const term = q.trim();
  const low = term.toLowerCase();

  const show_ = (h: PickerHit) => (h.bare ? h.name : `${base(h.symbol)}  ${h.name}`.trim());
  // Follow the parent: a cleared form clears the box, and a value set from
  // outside (a ?symbol= link, a default choice) shows up as picked.
  useEffect(() => {
    if (!value) { if (picked || !strict) { setQ(""); setPicked(null); } return; }
    if (value !== picked?.symbol && value !== q.trim().toUpperCase()) {
      const h = options?.find((o) => o.symbol === value) ?? { symbol: value, name: "" };
      setPicked(h); setQ(show_(h));
    }
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setSel(0), [term]);

  const wl = useQuery({ queryKey: ["watchlist"], queryFn: () => api.get<WatchlistData>("/api/watchlist"), staleTime: 5 * 60_000, enabled: !strict && mine });
  const remote = useQuery({ queryKey: ["picker", searchKey, term], queryFn: () => search(term), enabled: (!strict || nameSearch) && open && !picked && term.length >= minChars, staleTime: 60_000, retry: false });

  const rows: PickerHit[] = useMemo(() => {
    const has = (h: PickerHit) => h.symbol.toLowerCase().includes(low) || h.name.toLowerCase().includes(low);
    if (strict) {
      const named = new Map((remote.data ?? []).map((h) => [h.symbol, h.name]));
      // One row per symbol (a list can repeat one), each saying its exchange,
      // so RELIANCE.NS and RELIANCE.BO never look like the same row.
      const seen = new Set<string>();
      return options!.filter((h) => !seen.has(h.symbol) && !!seen.add(h.symbol))
        .map((h) => ({ ...h, name: h.name || named.get(h.symbol) || "", right: h.right ?? (exchange(h.symbol) || undefined) }))
        .filter((h) => !low || has(h) || named.has(h.symbol));
    }
    if (term.length < minChars) return [];
    const out: PickerHit[] = [];
    const seen = new Set<string>();
    if (mine) for (const i of wl.data?.items ?? []) {
      if (i.type === "mf" || !i.symbol || seen.has(i.symbol)) continue;
      const ex = exchange(i.symbol);
      const h = { symbol: i.symbol, name: i.label || base(i.symbol), right: ex ? `${ex} · In watchlist` : "In watchlist" };
      if (has(h)) { seen.add(h.symbol); out.push(h); }
    }
    for (const h of remote.data ?? []) { if (!seen.has(h.symbol)) { seen.add(h.symbol); out.push(h); } }
    return out.slice(0, 8);
  }, [strict, options, term, low, minChars, mine, wl.data, remote.data]);

  const pick = (h: PickerHit) => { setPicked(h); setQ(show_(h)); setOpen(false); onChange(h.symbol); onPick?.(h); };
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { setOpen(false); return; }
    if (!open || !rows.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(rows.length - 1, s + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(0, s - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); pick(rows[sel]); }
  };
  const show = open && !picked && (strict || term.length >= minChars);
  // The picked listing's exchange sits inside the box (not on a line under
  // it), so a picker lines up with the fields next to it in a form row.
  const tag = picked && !picked.bare ? exchange(picked.symbol) : "";

  return (
    <div className="f">
      <label htmlFor={id} className={hideLabel ? "sr-only" : undefined}>{label}</label>
      <div style={{ position: "relative" }}>
        <input id={id} autoComplete="off" role="combobox" aria-expanded={show} aria-controls={`${id}-list`} placeholder={placeholder} required={required} disabled={disabled} value={q}
          style={{ ...(hideLabel ? { marginTop: 0 } : {}), ...(tag ? { paddingRight: 56 } : {}) }}
          onChange={(e) => { setQ(e.target.value); setPicked(null); setOpen(true); onChange(strict ? "" : e.target.value.trim().toUpperCase()); }}
          onFocus={() => setOpen(true)} onClick={() => setOpen(true)} onBlur={() => setOpen(false)} onKeyDown={onKeyDown} />
        {tag && <span className="pill picker__exch" title={`${picked!.symbol}, listed on the ${tag}`}>{tag}</span>}
        {show && (
          <div className="suggest" id={`${id}-list`} role="listbox" style={{ top: "calc(100% + 6px)", right: "auto", minWidth: "100%", width: "max-content", maxWidth: "min(480px, calc(100vw - 32px))", maxHeight: 340, overflowY: "auto" }}>
            {rows.length === 0 && <div className="note" style={{ padding: 10 }}>{remote.isFetching ? "Searching" : strict && !options!.length ? "Nothing to choose from yet." : strict ? `Nothing in your list matches "${term}".` : `Nothing matches "${term}".`}</div>}
            {rows.map((h, i) => (
              <button key={h.symbol} type="button" role="option" aria-selected={i === sel} style={i === sel ? { background: "var(--action-tint)" } : undefined}
                onMouseDown={(e) => e.preventDefault()} onMouseEnter={() => setSel(i)} onClick={() => pick(h)}>
                <span style={{ minWidth: 0 }}>{!h.bare && <b>{base(h.symbol)} </b>}<span className="muted">{h.name}</span></span>
                {h.right && <span className="muted" style={{ flexShrink: 0 }}>{h.right}</span>}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
