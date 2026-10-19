import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { base } from "../lib/format";
import { setSettings, useSettings } from "../lib/settings";

/* eslint-disable @typescript-eslint/no-explicit-any */

// How long the Scorecard keeps snapshotting a stock. 0 = until stopped.
export const TRACK_DAYS: [number, string][] = [[7, "7 days"], [30, "30 days"], [90, "90 days"], [180, "6 months"], [365, "1 year"], [0, "Until I stop"]];
export const periodLabel = (days: number | null | undefined) => (!days ? "Until stopped" : TRACK_DAYS.find(([d]) => d === days)?.[1] ?? `${days} days`);

export function DaysSelect({ id, value, onChange, small, label }: { id: string; value: number; onChange: (d: number) => void; small?: boolean; label?: string }) {
  const known = TRACK_DAYS.some(([d]) => d === value);
  return (
    <select id={id} aria-label={label} value={value} onChange={(e) => onChange(Number(e.target.value))} className={small ? "select-sm" : undefined}>
      {!known && <option value={value}>{value} days</option>}
      {TRACK_DAYS.map(([d, l]) => <option key={d} value={d}>{l}</option>)}
    </select>
  );
}

type Source = "backtest" | "ai_lab" | "analyst";

// The "put this on the Scorecard" strip shown under a research result.
// With "add automatically" on (Scorecard page, or the checkbox here) it adds
// the stock as soon as a result arrives; otherwise it offers a button and a
// tracking period. `runId` changes whenever a new result arrives.
export function TrackOnScorecard({ symbol, source, runId, rule, what, after }: {
  symbol: string; source: Source; runId: unknown; what: string; after?: string;
  rule?: { strategy: string; cost: number };
}) {
  const s = useSettings();
  const qc = useQueryClient();
  const [days, setDays] = useState(s.trackDays);
  const [done, setDone] = useState<{ until: string | null; days: number | null } | null>(null);
  const add = useMutation({
    mutationFn: (d: number) => (rule
      ? api.post<any>("/api/scorecard/rule", { symbol, strategy: rule.strategy, cost: rule.cost, days: d || null })
      : api.post<any>("/api/scorecard/track", { symbols: [symbol], source, days: d || null })),
    onSuccess: (r) => {
      const t = (r?.tracked ?? []).find((x: any) => x.symbol === symbol.toUpperCase());
      setDone({ until: t?.until ?? null, days: t?.days ?? null });
      qc.invalidateQueries({ queryKey: ["tracked"] }); qc.invalidateQueries({ queryKey: ["scorecard"] });
    },
  });
  const last = useRef<unknown>(null);
  useEffect(() => {
    if (!runId || !symbol || runId === last.current) return;
    last.current = runId;
    setDone(null);
    if (s.autoTrack) add.mutate(s.trackDays);
  }, [runId, symbol]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!symbol || !runId) return null;

  return (
    <div className="trackbar">
      {done ? (
        <span>
          <b>On the Scorecard.</b> {base(symbol)} is tracked {done.until ? `until ${done.until}` : "until you stop it"}.{after ? ` ${after}` : ""}{" "}
          <Link className="link" to="/research/scorecard">Open Scorecard</Link>
        </span>
      ) : add.isPending ? (
        <span className="muted">Adding {base(symbol)} to the Scorecard</span>
      ) : (
        <>
          <span className="trackbar__text">Grade this later? Put {base(symbol)} on the Scorecard: {what}.</span>
          <label className="trackbar__days"><span>Track for</span><DaysSelect id={`td-${source}`} value={days} onChange={setDays} small /></label>
          <button type="button" className="btn btn--primary" style={{ height: 36 }} onClick={() => add.mutate(days)}>Add to Scorecard</button>
          <label className="trackbar__auto"><input type="checkbox" checked={s.autoTrack} onChange={(e) => { setSettings({ autoTrack: e.target.checked, trackDays: days }); if (e.target.checked) add.mutate(days); }} /> Always add automatically</label>
        </>
      )}
      {add.isError && <span className="loss">{(add.error as Error).message}</span>}
    </div>
  );
}
