import { getSettings } from "./settings";

// Indian grouping (12,84,560, lakh, crore) by default. Settings can switch to
// international grouping (1,284,560, million, billion).
const fmts = (locale: string) => ({ n0: new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }), n2: new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) });
const IN = fmts("en-IN"), US = fmts("en-US");
const intl = () => getSettings().numbers === "international";
const inr0 = { format: (v: number) => (intl() ? US : IN).n0.format(v) };
const inr2 = { format: (v: number) => (intl() ? US : IN).n2.format(v) };

export const dash = "\u2014";

export function money(v: number | null | undefined, decimals = 2): string {
  if (v == null || Number.isNaN(v)) return dash;
  return "\u20B9" + (decimals === 0 ? inr0 : inr2).format(v);
}

export function compact(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return dash;
  const abs = Math.abs(v);
  if (intl()) { if (abs >= 1e9) return "\u20B9" + (v / 1e9).toFixed(2) + " B"; if (abs >= 1e6) return "\u20B9" + (v / 1e6).toFixed(1) + " M"; return money(v, 0); }
  if (abs >= 1e12) return "\u20B9" + (v / 1e12).toFixed(2) + " L Cr";
  if (abs >= 1e7) return "\u20B9" + inr0.format(v / 1e7) + " Cr";
  if (abs >= 1e5) return "\u20B9" + (v / 1e5).toFixed(1) + " L";
  return money(v, 0);
}

export function pct(v: number | null | undefined, decimals = 2): string {
  if (v == null || Number.isNaN(v)) return dash;
  return (v >= 0 ? "+" : "") + v.toFixed(decimals) + "%";
}

export function signed(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return dash;
  return (v >= 0 ? "+" : "-") + "\u20B9" + inr0.format(Math.abs(v));
}

export const tone = (v: number | null | undefined) => (v == null ? "" : v >= 0 ? "gain" : "loss");

// Today as YYYY-MM-DD in the user's own timezone. toISOString() is UTC, so
// in India it reads as yesterday from midnight until 05:30.
export function localDate(d = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// "ACME.NS" -> "ACME"
export const base = (symbol: string | null | undefined) => (symbol ?? "").split(".")[0];
// Which exchange a Yahoo-style ticker trades on: RELIANCE.NS -> NSE, .BO -> BSE.
export const exchange = (symbol: string | null | undefined): string => {
  const s = (symbol ?? "").toUpperCase();
  return s.endsWith(".NS") ? "NSE" : s.endsWith(".BO") ? "BSE" : "";
};
