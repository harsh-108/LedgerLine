import { useCallback, useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BRAND } from "../lib/brand";
import { api } from "../lib/api";
import type { AuthStatus, Me } from "../lib/types";
import { Logo } from "../components/Icon";
import { GoogleButton } from "../components/GoogleButton";
import { ApiError } from "../lib/api";

export default function Login() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);

  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/auth/me"), retry: false });
  // First run: no users exist yet, so this form creates the first (admin) account.
  const status = useQuery({ queryKey: ["auth-status"], queryFn: () => api.get<AuthStatus>("/api/auth/status") });
  const firstRun = status.data?.has_users === false;

  const submit = useMutation({
    mutationFn: () => api.post(firstRun ? "/api/auth/setup" : "/api/auth/login", { username, password }),
    onSuccess: async () => { await qc.invalidateQueries({ queryKey: ["me"] }); navigate("/"); },
    meta: { quiet: true },
  });
  const google = useMutation({
    mutationFn: (credential: string) => api.post("/api/auth/google", { credential }),
    onSuccess: async () => { await qc.invalidateQueries({ queryKey: ["me"] }); navigate("/"); },
    meta: { quiet: true },
  });
  const onGoogle = useCallback((c: string) => google.mutate(c), [google]);
  const [resendEmail, setResendEmail] = useState("");
  const resend = useMutation({ mutationFn: () => api.post<{ ok: boolean; dev_verify_url?: string; mail_error?: string }>("/api/auth/resend", { email: resendEmail }), meta: { ok: "If that email is registered, a new link is on its way" } });
  const unverified = submit.error instanceof ApiError && submit.error.status === 403;

  if (me.data?.user) return <Navigate to="/" replace />;
  const onSubmit = (e: FormEvent) => { e.preventDefault(); if (username && password) submit.mutate(); };

  return (
    <div className="login">
      <aside className="login__side">
        <div className="brand" style={{ color: "#fff", fontSize: 22 }}><Logo size={32} /><span>{BRAND.name}</span></div>
        <h1>{firstRun ? "Set up your account." : "Welcome back."}</h1>
        <p>{firstRun ? "This first account becomes the admin. Everything stays on this machine." : "Your watchlists, alerts, and portfolio are where you left them."}</p>
      </aside>
      <main className="login__main">
        <form className="login__form" onSubmit={onSubmit}>
          <h2>{firstRun ? "Create the admin account" : "Log in"}</h2>
          <div className="field">
            <label htmlFor="u">Username</label>
            <input id="u" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Your username" />
          </div>
          <div className="field" style={{ position: "relative" }}>
            <label htmlFor="p">Password</label>
            <input id="p" type={show ? "text" : "password"} autoComplete={firstRun ? "new-password" : "current-password"} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Your password" />
            <button type="button" className="btn btn--quiet" style={{ position: "absolute", right: 4, bottom: 5 }} onClick={() => setShow((s) => !s)}>{show ? "Hide" : "Show"}</button>
          </div>
          {(submit.isError || google.isError) && <div className="error" role="alert">{((submit.error ?? google.error) as Error).message}</div>}
          {unverified && <div className="field" style={{ marginTop: 8 }}><label htmlFor="re">Resend the confirmation email</label><div style={{ display: "flex", gap: 8 }}><input id="re" type="email" value={resendEmail} onChange={(e) => setResendEmail(e.target.value)} placeholder="Your email" /><button type="button" className="btn" disabled={!resendEmail || resend.isPending} onClick={() => resend.mutate()}>Resend</button></div>{resend.data?.dev_verify_url && <p className="note">The email couldn't be sent{resend.data.mail_error ? ` (${resend.data.mail_error})` : ""}. Development mode, so here is the link directly: <a href={resend.data.dev_verify_url} style={{ textDecoration: "underline" }}>confirm now</a></p>}</div>}
          <button className="login__submit" type="submit" disabled={submit.isPending || !username || !password}>
            {submit.isPending ? (<><span className="spin" />Checking your details</>) : firstRun ? "Create account" : "Log in"}
          </button>
          {!firstRun && <GoogleButton clientId={status.data?.google_client_id} onCredential={onGoogle} />}
          {!firstRun && <div className="note"><Link to="/forgot" style={{ textDecoration: "underline" }}>Forgot your password?</Link> · New here? <Link to="/signup" style={{ textDecoration: "underline" }}>Create an account</Link></div>}
        </form>
      </main>
    </div>
  );
}
