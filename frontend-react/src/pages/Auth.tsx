import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BRAND } from "../lib/brand";
import { api } from "../lib/api";
import type { AuthStatus } from "../lib/types";
import { Logo } from "../components/Icon";
import { GoogleButton } from "../components/GoogleButton";

function Frame({ title, blurb, children }: { title: string; blurb: string; children: ReactNode }) {
  return (
    <div className="login">
      <aside className="login__side">
        <div className="brand" style={{ color: "#fff", fontSize: 22 }}><Logo size={32} /><span>{BRAND.name}</span></div>
        <h1>{title}</h1>
        <p>{blurb}</p>
      </aside>
      <main className="login__main">{children}</main>
    </div>
  );
}

function useAuthStatus() {
  return useQuery({ queryKey: ["auth-status"], queryFn: () => api.get<AuthStatus>("/api/auth/status") });
}

// --------------------------------------------------------------- Signup
export function Signup() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const status = useAuthStatus();
  const [f, setF] = useState({ invite: params.get("invite") ?? "", email: "", username: "", password: "" });
  const [show, setShow] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  const submit = useMutation({
    mutationFn: () => api.post<{ ok: boolean; user: string; verify_sent: boolean; dev_verify_url?: string; mail_error?: string }>("/api/auth/signup", { email: f.email, username: f.username, password: f.password, invite_code: f.invite || null }),
    meta: { quiet: true },
  });
  const google = useMutation({
    mutationFn: (credential: string) => api.post<{ ok: boolean }>("/api/auth/google", { credential, invite_code: f.invite || null }),
    onSuccess: async () => { await qc.invalidateQueries({ queryKey: ["me"] }); navigate("/"); },
    meta: { quiet: true },
  });
  const onGoogle = useCallback((c: string) => google.mutate(c), [google]);
  const inviteRequired = status.data?.invite_required !== false;
  const googleNeedsInvite = inviteRequired && status.data?.google_invite_required === true;
  const canSubmit = f.email && f.username && f.password.length >= 8 && (!inviteRequired || f.invite);
  const onSubmit = (e: FormEvent) => { e.preventDefault(); if (canSubmit) submit.mutate(); };

  if (status.data && status.data.has_users === false) return <Frame title="First run." blurb="Create the admin account from the sign-in page."><div className="login__form"><Link className="btn btn--primary" to="/login">Go to sign in</Link></div></Frame>;

  if (submit.isSuccess) {
    return (
      <Frame title="Check your email." blurb="One click confirms your address and signs you in.">
        <div className="login__form">
          <h2>Almost there</h2>
          <p className="secondary">We sent a confirmation link to <b>{f.email}</b>. It's valid for 24 hours.</p>
          {submit.data.dev_verify_url && <p className="note">The email couldn't be sent{submit.data.mail_error ? ` (${submit.data.mail_error})` : ""}. Development mode, so here is the link directly: <a href={submit.data.dev_verify_url} style={{ textDecoration: "underline" }}>confirm now</a></p>}
          <Link className="btn" to="/login" style={{ marginTop: 12 }}>Back to sign in</Link>
        </div>
      </Frame>
    );
  }

  return (
    <Frame title="Create your account." blurb="Your own watchlists, alerts and portfolio. Nothing is shared with other users.">
      <form className="login__form" onSubmit={onSubmit}>
        <h2>Sign up</h2>
        {inviteRequired && <div className="field"><label htmlFor="inv">Invite code</label><input id="inv" value={f.invite} onChange={set("invite")} placeholder="From whoever invited you" />{!googleNeedsInvite && status.data?.google_client_id && <span className="note">Needed for email sign-up only. Signing up with Google below needs no code.</span>}</div>}
        <div className="field"><label htmlFor="em">Email</label><input id="em" type="email" autoComplete="email" value={f.email} onChange={set("email")} placeholder="you@example.com" /></div>
        <div className="field"><label htmlFor="un">Username</label><input id="un" autoComplete="username" value={f.username} onChange={set("username")} placeholder="3-30 letters, digits, dots or dashes" /></div>
        <div className="field" style={{ position: "relative" }}>
          <label htmlFor="pw">Password, 8 or more characters</label>
          <input id="pw" type={show ? "text" : "password"} autoComplete="new-password" value={f.password} onChange={set("password")} />
          <button type="button" className="btn btn--quiet" style={{ position: "absolute", right: 4, bottom: 5 }} onClick={() => setShow((s) => !s)}>{show ? "Hide" : "Show"}</button>
        </div>
        {(submit.isError || google.isError) && <div className="error" role="alert">{((submit.error ?? google.error) as Error).message}</div>}
        <button className="login__submit" type="submit" disabled={submit.isPending || !canSubmit}>{submit.isPending ? <><span className="spin" />Creating your account</> : "Create account"}</button>
        <GoogleButton clientId={status.data?.google_client_id} onCredential={onGoogle} text="signup_with" />
        <div className="note">By signing up you agree to the <Link to="/more/learn" style={{ textDecoration: "underline" }}>terms and privacy policy</Link>. Already have an account? <Link to="/login" style={{ textDecoration: "underline" }}>Sign in</Link>.</div>
      </form>
    </Frame>
  );
}

// --------------------------------------------------------------- Verify
export function Verify() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const token = params.get("token") ?? "";
  const verify = useMutation({
    mutationFn: () => api.get<{ ok: boolean }>(`/api/auth/verify?token=${encodeURIComponent(token)}`),
    onSuccess: async () => { await qc.invalidateQueries({ queryKey: ["me"] }); navigate("/", { replace: true }); },
    meta: { quiet: true },
  });
  useEffect(() => { if (token) verify.mutate(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [token]);
  return (
    <Frame title="Confirming your email." blurb="This takes a moment.">
      <div className="login__form">
        <h2>{verify.isError ? "That link didn't work" : "Confirming"}</h2>
        {!token && <div className="error">The link is missing its code. Open it from the email again.</div>}
        {verify.isPending && <p className="secondary"><span className="spin" /> Checking the link</p>}
        {verify.isError && <><div className="error" role="alert">{(verify.error as Error).message}</div><Link className="btn" to="/login" style={{ marginTop: 12 }}>Back to sign in</Link></>}
      </div>
    </Frame>
  );
}

// --------------------------------------------------------------- Forgot
export function Forgot() {
  const [email, setEmail] = useState("");
  const submit = useMutation({ mutationFn: () => api.post<{ ok: boolean; dev_reset_url?: string; mail_error?: string }>("/api/auth/forgot", { email }), meta: { quiet: true } });
  return (
    <Frame title="Reset your password." blurb="We'll email you a link that's valid for an hour.">
      <form className="login__form" onSubmit={(e) => { e.preventDefault(); if (email) submit.mutate(); }}>
        <h2>Forgot your password</h2>
        {submit.isSuccess ? (
          <>
            <p className="secondary">If an account uses <b>{email}</b>, a reset link is on its way.</p>
            {submit.data.dev_reset_url && <p className="note">The email couldn't be sent{submit.data.mail_error ? ` (${submit.data.mail_error})` : ""}. Development mode, so: <a href={submit.data.dev_reset_url} style={{ textDecoration: "underline" }}>reset now</a></p>}
          </>
        ) : (
          <>
            <div className="field"><label htmlFor="fe">Email</label><input id="fe" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
            {submit.isError && <div className="error" role="alert">{(submit.error as Error).message}</div>}
            <button className="login__submit" type="submit" disabled={submit.isPending || !email}>{submit.isPending ? <><span className="spin" />Sending</> : "Send reset link"}</button>
          </>
        )}
        <div className="note"><Link to="/login" style={{ textDecoration: "underline" }}>Back to sign in</Link></div>
      </form>
    </Frame>
  );
}

// --------------------------------------------------------------- Reset
export function Reset() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const token = params.get("token") ?? "";
  const [pw, setPw] = useState("");
  const submit = useMutation({
    mutationFn: () => api.post<{ ok: boolean }>("/api/auth/reset", { token, password: pw }),
    onSuccess: async () => { await qc.invalidateQueries({ queryKey: ["me"] }); navigate("/", { replace: true }); },
    meta: { quiet: true },
  });
  return (
    <Frame title="Choose a new password." blurb="Other devices will be signed out.">
      <form className="login__form" onSubmit={(e) => { e.preventDefault(); if (pw.length >= 8) submit.mutate(); }}>
        <h2>New password</h2>
        {!token && <div className="error">The link is missing its code. Open it from the email again.</div>}
        <div className="field"><label htmlFor="rp">Password, 8 or more characters</label><input id="rp" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} /></div>
        {submit.isError && <div className="error" role="alert">{(submit.error as Error).message}</div>}
        <button className="login__submit" type="submit" disabled={submit.isPending || pw.length < 8 || !token}>{submit.isPending ? <><span className="spin" />Saving</> : "Set password and sign in"}</button>
      </form>
    </Frame>
  );
}
