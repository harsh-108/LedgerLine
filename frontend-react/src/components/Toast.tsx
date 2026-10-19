import { useEffect, useState } from "react";

// Notifications. `toast("Holding added")` from anywhere. Mutations get them
// automatically: errors always, successes when the mutation sets meta.ok.
export type ToastKind = "ok" | "err";
interface T { id: number; text: string; kind: ToastKind }
let items: T[] = [];
let seq = 1;
const subs = new Set<(t: T[]) => void>();
const emit = () => subs.forEach((f) => f(items));

export function toast(text: string, kind: ToastKind = "ok") {
  const id = seq++;
  items = [...items, { id, text, kind }].slice(-4);
  emit();
  setTimeout(() => { items = items.filter((t) => t.id !== id); emit(); }, kind === "err" ? 6000 : 3200);
}

export function Toaster() {
  const [list, setList] = useState<T[]>(items);
  useEffect(() => { subs.add(setList); return () => { subs.delete(setList); }; }, []);
  return (
    <div className="toasts" role="status" aria-live="polite">
      {list.map((t) => (
        <div key={t.id} className={`toast toast--${t.kind}`}>
          <span className="toast__dot" />{t.text}
          <button aria-label="Dismiss" onClick={() => { items = items.filter((x) => x.id !== t.id); emit(); }}>x</button>
        </div>
      ))}
    </div>
  );
}
