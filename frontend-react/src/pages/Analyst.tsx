import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useWatchSymbols } from "../lib/symbols";
import { Card, ErrorBox, PageHead, Pill } from "../components/ui";
import { Icon } from "../components/Icon";
import { SymbolSelect } from "../components/Section";
import { TrackOnScorecard } from "../components/TrackOnScorecard";

/* eslint-disable @typescript-eslint/no-explicit-any */
type ToolUsed = string | { tool: string; args?: unknown };
interface Msg { who: "me" | "ai"; text: string; tools?: ToolUsed[] }
// Users should know where their questions go before they type them.
const AI_NOTICE = "Privacy: answers come from an outside AI service, which sees your holdings and the filings it reads so it can answer. Personal details (your name, email, phone, PAN, Aadhaar, bank, demat and card numbers) are masked before anything is sent, and the app puts them back into the answer. Free AI services may keep what they receive, so don't type passwords here.";
const IDEAS = ["Which of my watchlist stocks look strongest on quality and trend?", "How did golden crosses work out for TCS?", "Summarise the risks in the latest filing I uploaded"];

export default function Analyst() {
  const symbols = useWatchSymbols();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [sym, setSym] = useState("");
  // Answers given while a stock was selected: each one can put that stock
  // on the Scorecard (automatically, or with a button).
  const [asked, setAsked] = useState<{ sym: string; n: number } | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const status = useQuery({ queryKey: ["analyst-status"], queryFn: () => api.get<any>("/api/analyst/status") });
  const docs = useQuery({ queryKey: ["docs", sym], queryFn: () => api.get<{ documents: any[] }>(`/api/docs/${encodeURIComponent(sym)}`), enabled: !!sym });
  const chat = useMutation({
    mutationFn: (t: string) => api.post<any>("/api/analyst/chat", { text: t, symbol: sym || undefined }),
    onSuccess: (d, _t) => { setMsgs((m) => [...m, { who: "ai", text: d.reply ?? d.text ?? d.answer ?? JSON.stringify(d), tools: d.tools_used }]); status.refetch(); if (sym) setAsked((a) => ({ sym, n: (a?.n ?? 0) + 1 })); },
    onError: (e) => setMsgs((m) => [...m, { who: "ai", text: `The analyst is unavailable: ${(e as Error).message}` }]),
  });
  const reset = useMutation({ mutationFn: () => api.post("/api/analyst/reset"), meta: { ok: "New chat started" }, onSuccess: () => setMsgs([]) });
  const upload = useMutation({
    mutationFn: async (file: File) => { const fd = new FormData(); fd.append("symbol", sym); fd.append("file", file); const r = await fetch("/api/docs/upload", { method: "POST", body: fd, credentials: "same-origin" }); if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText); return r.json(); },
    meta: { ok: "Document added. The analyst can read it now." },
    onSuccess: () => docs.refetch(),
  });
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, chat.isPending]);
  const send = (t: string) => { if (!t.trim() || chat.isPending) return; setMsgs((m) => [...m, { who: "me", text: t }]); setText(""); chat.mutate(t); };
  const onSubmit = (e: FormEvent) => { e.preventDefault(); send(text); };
  const ready = status.data?.llm_ready;

  return (
    <>
      <PageHead title="AI analyst" sub="Ask in plain language. It pulls from the screener, backtests, live quotes, and the filings you add." />
      {status.data && !ready && <div className="callout"><span><b>No AI key set up.</b> Add OPENROUTER_API_KEY or GROQ_API_KEY to the .env file and restart the backend. The rest of the app works without it.</span></div>}
      <div className="row" style={{ alignItems: "flex-start" }}>
        <div style={{ width: 320, flexShrink: 0, display: "flex", flexDirection: "column", gap: 20 }}>
          <Card title="Your documents" sub="The analyst reads filings you add">
            <div style={{ marginTop: 12 }}><SymbolSelect id="ds" value={sym} onChange={setSym} symbols={symbols} label="Filings for" /></div>
            <div style={{ marginTop: 8 }}>
              {docs.data?.documents.map((d, i) => <div className="kv" key={i}><span>{d.title ?? d.filename ?? d.name ?? "Document"}</span><span>{d.pages ? `${d.pages} p` : ""}</span></div>)}
              {sym && docs.data?.documents.length === 0 && <div className="note">None yet for this stock.</div>}
            </div>
            <label className="btn" style={{ marginTop: 12, cursor: sym ? "pointer" : "not-allowed", opacity: sym ? 1 : 0.6 }}>Upload a PDF<input type="file" accept="application/pdf" disabled={!sym} onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} style={{ display: "none" }} /></label>
            {upload.isPending && <div className="note">Reading the file</div>}{upload.isError && <ErrorBox error={upload.error} />}
            {asked && asked.sym === sym && <TrackOnScorecard symbol={sym} source="analyst" runId={`${asked.sym}:${asked.n}`} what="the app's daily verdict on it is written down and graded later" />}
          </Card>
          <Card title="Assistant">
            <div style={{ marginTop: 8 }}>
              <div className="kv"><span>Status</span><span>{status.data?.llm_ready ? "Ready" : "Unavailable"}</span></div>
              {status.data?.quota && <div className="kv"><span>Questions today</span><span>{status.data.quota.limit == null ? `${status.data.quota.used} (unlimited)` : `${status.data.quota.left} of ${status.data.quota.limit} left`}</span></div>}
              {status.data?.providers && (<>
                {status.data.providers.map((p: any, i: number) => <div className="kv" key={i}><span>{i + 1}. {typeof p === "string" ? p : p.name ?? "provider"}</span><span>{typeof p === "object" ? p.status ?? p.model ?? "" : ""}</span></div>)}
                <div className="kv"><span>Web search</span><span>{status.data?.web_search ? "On" : "Off"}</span></div>
              </>)}
            </div>
          </Card>
        </div>
        <section className="card card--flush chat grow">
          <div className="card__head" style={{ borderBottom: "1px solid var(--line)", paddingBottom: 14 }}><h2>Analyst</h2><button className="btn" style={{ height: 36 }} onClick={() => reset.mutate()}>New chat</button></div>
          <div className="chat__msgs">
            {msgs.length === 0 && (<div style={{ margin: "auto", textAlign: "center", maxWidth: 480 }}><p className="secondary" style={{ lineHeight: 1.6 }}>Every answer lists the tools it used, so you can check the work. It reads your stored data and documents and gives a buy, hold or sell call with its reasons.</p><p className="note" style={{ lineHeight: 1.6, marginTop: 10 }}>{AI_NOTICE}</p><div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 16 }}>{IDEAS.map((t) => <button key={t} className="btn" style={{ height: "auto", padding: "10px 14px", whiteSpace: "normal" }} onClick={() => send(t)}>{t}</button>)}</div></div>)}
            {msgs.map((m, i) => (<div key={i} style={{ alignSelf: m.who === "me" ? "flex-end" : "flex-start", maxWidth: "82%" }}>{m.tools && m.tools.length > 0 && <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>{m.tools.map((t, k) => <Pill key={k}>{(typeof t === "string" ? t : t?.tool ?? "").replace(/_/g, " ")}</Pill>)}{m.tools.some((t: any) => t?.injection_flagged) && <span title="A filing or web page in this answer contained instructions aimed at the AI. They were ignored; treat that source with care."><Pill kind="loss">Source tried to instruct the AI, ignored</Pill></span>}</div>}<div className={`msg msg--${m.who}`} style={{ maxWidth: "100%" }}>{m.text}</div></div>))}
            {chat.isPending && <div className="msg msg--ai">Working on it</div>}
            <div ref={end} />
          </div>
          <form className="chat__input" onSubmit={onSubmit}><label htmlFor="aq" className="sr-only">Ask the analyst</label><input id="aq" value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask about a stock, a fund, or your own filings" maxLength={4000} /><button className="icon-btn" style={{ background: "var(--action)", borderColor: "var(--action)", color: "var(--on-action)", width: 48, height: 48 }} aria-label="Send" disabled={chat.isPending}><Icon name="send" size={19} /></button></form>
        </section>
      </div>
      <p className="note">Calls are based on your documents and stored, possibly delayed data. Not investment advice: you make the trade. {AI_NOTICE}</p>
    </>
  );
}
