import { Link } from "react-router-dom";
import { base } from "../lib/format";
import { Term } from "./InfoTip";

type Row = Record<string, unknown>;
const nf = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
const isSigned = (k: string) => /%|\bz\b|Net|P&L|ret|edge|Score/i.test(k) && !/ROE|Margin|yield|Weight|hit|win|accuracy/i.test(k);

// Renders whatever records the backend returns. Used where the column set is
// decided by the server (screener, rankings, trades, tax report).
export function RecordsTable({ rows, columns, symbolKey = "Symbol", empty = "No rows." }: {
  rows: Row[]; columns?: string[]; symbolKey?: string; empty?: string;
}) {
  if (!rows || rows.length === 0) return <div className="note" style={{ padding: 20 }}>{empty}</div>;
  const cols = columns ?? Object.keys(rows[0]).filter((k) => typeof rows[0][k] !== "object" || rows[0][k] === null);
  return (
    <div className="table-wrap">
      <table className="table">
        <thead><tr>{cols.map((c) => <th key={c} className={typeof rows[0][c] === "number" ? "right" : ""}><Term>{c}</Term></th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {cols.map((c) => {
                const v = r[c];
                if (c === symbolKey && typeof v === "string") return <td key={c} className="name"><Link to={`/stocks/${encodeURIComponent(v)}`}>{base(v)}</Link></td>;
                if (v == null || v === "") return <td key={c} className="right muted">&mdash;</td>;
                if (typeof v === "number") {
                  const cls = isSigned(c) ? (v >= 0 ? "gain" : "loss") : "";
                  return <td key={c} className={`right ${cls}`}>{isSigned(c) && v > 0 ? "+" : ""}{nf.format(v)}</td>;
                }
                if (typeof v === "boolean") return <td key={c}>{v ? "Yes" : "No"}</td>;
                return <td key={c}>{String(v)}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
