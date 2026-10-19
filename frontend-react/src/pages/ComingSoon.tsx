import { NavLink } from "react-router-dom";
import type { NavItem } from "../lib/nav";
import { Card, PageHead } from "../components/ui";

// Placeholder for a route that is wired into navigation but not ported yet.
// It names the mockup to follow and the backend endpoints it will call.
export default function ComingSoon({ item, siblings }: { item: NavItem; siblings?: NavItem[] }) {
  return (
    <>
      <PageHead title={item.label} sub="Needs a new backend endpoint before it can show real data" />
      {siblings && (
        <nav className="subnav" aria-label="Section">
          {siblings.map((s) => <NavLink key={s.to} to={s.to} className={({ isActive }) => (isActive ? "active" : "")}>{s.label}</NavLink>)}
        </nav>
      )}
      <Card title="Not built yet" sub={`Design to follow: the "${item.mock ?? item.label}" screen on the canvas`}>
        <p className="secondary" style={{ lineHeight: 1.6, maxWidth: "70ch" }}>The existing backend has no data source for this page yet. Once the endpoint below exists, build the page in <code>src/pages/</code> and swap it into <code>src/App.tsx</code>.</p>
        {item.endpoints && item.endpoints.length > 0 && (
          <>
            <div className="sub" style={{ marginTop: 8 }}>Backend endpoints it will use</div>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18, lineHeight: 1.8 }}>{item.endpoints.map((e) => <li key={e}><code>{e}</code></li>)}</ul>
          </>
        )}
      </Card>
    </>
  );
}
