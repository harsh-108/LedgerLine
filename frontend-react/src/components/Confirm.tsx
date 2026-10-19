import { useEffect, useRef, useState, type ReactNode } from "react";

// An in-app "are you sure?" dialog, so destructive actions never fall back
// to the browser's own confirm() box (which says "127.0.0.1:8000 says" and
// ignores the theme). Works like toast(): call it from anywhere,
//
//   if (await confirmDialog({ title: "Delete X?", danger: true })) ...
//
// `Confirmer` is mounted once in AppShell. Escape or a click outside the
// card cancels; the Cancel button takes focus first for destructive asks.
export interface ConfirmOptions {
  title: string;
  body?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}
interface Pending extends ConfirmOptions { resolve: (ok: boolean) => void }

let pending: Pending | null = null;
const subs = new Set<(p: Pending | null) => void>();
const emit = () => subs.forEach((f) => f(pending));

export function confirmDialog(opts: ConfirmOptions): Promise<boolean> {
  if (pending) pending.resolve(false);            // one question at a time
  return new Promise((resolve) => { pending = { ...opts, resolve }; emit(); });
}

function settle(ok: boolean) {
  const p = pending;
  pending = null;
  emit();
  p?.resolve(ok);
}

export function Confirmer() {
  const [p, setP] = useState<Pending | null>(pending);
  useEffect(() => { subs.add(setP); return () => { subs.delete(setP); }; }, []);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const okRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!p) return;
    (p.danger ? cancelRef : okRef).current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") settle(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [p]);

  if (!p) return null;
  return (
    <div className="dialog" role="presentation" onClick={(e) => { if (e.target === e.currentTarget) settle(false); }}>
      <div className="dialog__card" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
        <h2 id="dialog-title" className="dialog__title">{p.title}</h2>
        {p.body && <div className="dialog__body">{p.body}</div>}
        <div className="dialog__actions">
          <button ref={cancelRef} type="button" className="btn" onClick={() => settle(false)}>{p.cancelLabel ?? "Cancel"}</button>
          <button ref={okRef} type="button" className={`btn ${p.danger ? "btn--danger" : "btn--primary"}`} onClick={() => settle(true)}>{p.confirmLabel ?? "OK"}</button>
        </div>
      </div>
    </div>
  );
}
