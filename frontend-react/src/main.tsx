import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { toast } from "./components/Toast";
import App from "./App";
import { BRAND } from "./lib/brand";
import { applyToDocument, getSettings } from "./lib/settings";
import "./styles/global.css";

// Every failed action shows a notification. A successful one does too when the
// mutation sets meta.ok (a string, or a function of the result and variables).
const mutationCache = new MutationCache({
  onError: (e, _v, _c, m) => { if (!m.meta?.quiet) toast(e instanceof Error ? e.message : "Something went wrong", "err"); },
  onSuccess: (data, vars, _ctx, m) => {
    const ok = m.meta?.ok as string | ((d: unknown, v: unknown) => string) | undefined;
    if (ok && getSettings().confirmations) toast(typeof ok === "function" ? ok(data, vars) : ok);
  },
});

document.title = BRAND.name;

const queryClient = new QueryClient({
  mutationCache,
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: 1 } },
});

applyToDocument();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
