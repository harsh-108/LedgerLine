// Inline stroke icons, the same set the mockups use.
const PATHS: Record<string, string> = {
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4",
  bell: "M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 20h4",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z",
  star: "M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  pause: "M8 5v14M16 5v14",
  play: "M7 4l13 8-13 8z",
  book: "M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h10",
  bulb: "M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5V15h8v-1.5A6 6 0 0 0 12 3z",
  plus: "M12 5v14M5 12h14",
  send: "M4 12l16-8-6 16-3-7z",
  x: "M6 6l12 12M18 6L6 18",
  upload: "M12 16V5M7 9l5-5 5 5M5 20h14",
  download: "M12 4v11M7 11l5 5 5-5M5 20h14",
  logout: "M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10",
};

export function Icon({ name, size = 18 }: { name: keyof typeof PATHS | string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ flexShrink: 0 }}>
      <path d={PATHS[name] ?? ""} />
    </svg>
  );
}

import { BRAND, type Mark } from "../lib/brand";

// Four marks on the same marigold tile. `loading` redraws the stroke in a loop.
const MARKS: Record<Mark, JSX.Element> = {
  // a rising price line
  line: <polyline className="mk" points="6,19 11,13 15,16 22,8" />,
  // a loupe with a tick inside: look closely before you decide
  loupe: <><circle className="mk" cx="12.5" cy="12.5" r="6" /><path className="mk" d="M17 17l5 5" /><path className="mk" d="M10 12.8l2 2 3.2-4" /></>,
  // a balance: evidence for on one side, against on the other
  scale: <><path className="mk" d="M14 6v16M9 22h10M6 10l16-2" /><circle className="mk" cx="6.5" cy="14.5" r="2.4" /><circle className="mk" cx="21.5" cy="12.5" r="2.4" /></>,
  // a touchstone streak: the old test for real gold
  streak: <><path className="mk" d="M7 20L20 7" /><path className="mk" d="M7 14l6-6M14 21l7-7" style={{ opacity: 0.55 }} /></>,
};

export function Logo({ size = 28, loading = false, mark = BRAND.mark }: { size?: number; loading?: boolean; mark?: Mark }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden="true" className={`logo ${loading ? "logo--loading" : ""}`}>
      <rect width="28" height="28" rx="8" fill="#F2B33D" />
      <g fill="none" stroke="#10233F" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">{MARKS[mark]}</g>
    </svg>
  );
}
