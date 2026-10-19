import { useEffect, useRef } from "react";

declare global { interface Window { google?: any } }

/** Google Identity Services button. Renders nothing without a client id.
 *  Loads the GIS script once; hands the ID token (credential) to onCredential. */
export function GoogleButton({ clientId, onCredential, text = "signin_with" }: { clientId?: string; onCredential: (credential: string) => void; text?: "signin_with" | "signup_with" | "continue_with" }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!clientId || !ref.current) return;
    const render = () => {
      if (!window.google?.accounts?.id || !ref.current) return;
      window.google.accounts.id.initialize({ client_id: clientId, callback: (r: { credential: string }) => onCredential(r.credential) });
      window.google.accounts.id.renderButton(ref.current, { theme: "outline", size: "large", width: 320, text });
    };
    if (window.google?.accounts?.id) { render(); return; }
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client"; s.async = true; s.defer = true; s.onload = render;
    document.head.appendChild(s);
  }, [clientId, onCredential, text]);
  if (!clientId) return null;
  return <div ref={ref} style={{ display: "flex", justifyContent: "center", marginTop: 8 }} />;
}
