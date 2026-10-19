import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: "40px 0" }}>
      <svg width="520" height="180" viewBox="0 0 520 180" aria-hidden="true" style={{ maxWidth: "100%" }}>
        <polyline points="6,40 60,36 110,30 160,33 210,22 260,18 300,20 330,70 360,120 390,150 430,165 514,172" fill="none" stroke="var(--loss)" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" />
      </svg>
      <div style={{ fontFamily: "var(--font-display)", fontSize: 96, fontWeight: 700, letterSpacing: -3, lineHeight: 1 }}>404</div>
      <h1 style={{ marginTop: 12, fontSize: 28 }}>This page has been delisted</h1>
      <p className="secondary" style={{ maxWidth: "46ch", lineHeight: 1.6 }}>The link may be old, or the symbol may have changed. Your watchlists and portfolio are fine.</p>
      <Link className="btn btn--primary" to="/" style={{ height: 48, marginTop: 12 }}>Go to Home</Link>
    </div>
  );
}
