import { useSyncExternalStore } from "react";

// Preferences, saved in this browser. `useSettings()` re-renders on change,
// `getSettings()` reads them outside React (formatters, notifications).
export interface Settings {
  explain: boolean;        // plain-language "At a glance" readings
  tips: boolean;           // the "i" buttons
  candles: boolean;        // charts open as candlesticks
  range: "1M" | "6M" | "1Y" | "5Y" | "Max";
  numbers: "indian" | "international";
  theme: "light" | "dark" | "device";
  nav: "top" | "side";
  updown: "green-up" | "red-up";
  ribbon: boolean;
  ribbonShows: "all" | "held" | "watch";
  ribbonSpeed: 9 | 6 | 4;
  density: "comfortable" | "compact";
  confirmations: boolean;  // success notifications (errors always show)
  autoTrack: boolean;      // research runs put the stock on the Scorecard by themselves
  trackDays: number;       // default tracking period in days, 0 = until stopped
}
const DEFAULTS: Settings = { explain: true, tips: true, candles: true, range: "1Y", numbers: "indian", theme: "light", nav: "top", updown: "green-up", ribbon: true, ribbonShows: "all", ribbonSpeed: 6, density: "comfortable", confirmations: true, autoTrack: false, trackDays: 90 };
const KEY = "settings";

function load(): Settings {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "{}");
    // carry over the three older single keys once
    const legacy: Partial<Settings> = {};
    if (localStorage.getItem("theme") === "dark") legacy.theme = "dark";
    if (localStorage.getItem("chartType") === "Line") legacy.candles = false;
    return { ...DEFAULTS, ...legacy, ...saved };
  } catch { return DEFAULTS; }
}
let current = load();
const subs = new Set<() => void>();

export function applyToDocument(s: Settings = current) {
  const el = document.documentElement;
  const dark = s.theme === "dark" || (s.theme === "device" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  if (dark) el.dataset.theme = "dark"; else delete el.dataset.theme;
  el.dataset.updown = s.updown;
  el.dataset.density = s.density;
}
export const getSettings = () => current;
export function setSettings(patch: Partial<Settings>) {
  current = { ...current, ...patch };
  localStorage.setItem(KEY, JSON.stringify(current));
  applyToDocument();
  subs.forEach((f) => f());
}
export function useSettings(): Settings {
  return useSyncExternalStore((f) => { subs.add(f); return () => { subs.delete(f); }; }, () => current);
}
window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => applyToDocument());
