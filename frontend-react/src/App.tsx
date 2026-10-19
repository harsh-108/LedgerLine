import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "./lib/api";
import type { Me } from "./lib/types";
import { AppShell } from "./components/AppShell";
import { Logo } from "./components/Icon";
import Login from "./pages/Login";
import { Forgot, Reset, Signup, Verify } from "./pages/Auth";
import Home from "./pages/Home";
import Watchlists from "./pages/Watchlists";
import Stock from "./pages/Stock";
import Portfolio from "./pages/Portfolio";
import PortfolioTools from "./pages/PortfolioTools";
import Funds from "./pages/Funds";
import Screener from "./pages/Screener";
import Analyst from "./pages/Analyst";
import { AILab, Backtest, Journal, Scorecard } from "./pages/Research";
import { Calendar, Ipos, News } from "./pages/Feeds";
import { Admin, Alerts, Calculators, Compare, Learn, Reports } from "./pages/Misc";
import Settings from "./pages/Settings";
import FundDetail from "./pages/FundDetail";
import NotFound from "./pages/NotFound";

// Everything inside needs a session. The backend answers 401 when there is none.
function RequireAuth() {
  const location = useLocation();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/auth/me"), retry: false });
  if (me.isLoading) return <div style={{ height: "100%", display: "grid", placeItems: "center" }}><Logo size={56} loading /></div>;
  const signedOut = (me.error instanceof ApiError && me.error.status === 401) || (me.data && !me.data.user);
  if (signedOut) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/verify" element={<Verify />} />
      <Route path="/forgot" element={<Forgot />} />
      <Route path="/reset" element={<Reset />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route index element={<Home />} />
          <Route path="watchlists" element={<Watchlists />} />
          <Route path="stocks/:symbol" element={<Stock />} />
          <Route path="portfolio" element={<Portfolio />} />
          <Route path="portfolio/tools" element={<PortfolioTools />} />
          <Route path="funds" element={<Funds />} />
          <Route path="funds/:scheme" element={<FundDetail />} />
          <Route path="screener" element={<Screener />} />
          <Route path="analyst" element={<Analyst />} />
          <Route path="research/ai-lab" element={<AILab />} />
          <Route path="research/backtest" element={<Backtest />} />
          <Route path="research/scorecard" element={<Scorecard />} />
          <Route path="research/journal" element={<Journal />} />
          <Route path="alerts" element={<Alerts />} />
          <Route path="compare" element={<Compare />} />
          <Route path="settings" element={<Settings />} />
          <Route path="more/calculators" element={<Calculators />} />
          <Route path="more/learn" element={<Learn />} />
          <Route path="more/reports" element={<Reports />} />
          <Route path="more/admin" element={<Admin />} />
          <Route path="news" element={<News />} />
          <Route path="more/ipos" element={<Ipos />} />
          <Route path="more/calendar" element={<Calendar />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Route>
    </Routes>
  );
}
