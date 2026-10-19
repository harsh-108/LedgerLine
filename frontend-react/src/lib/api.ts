// One place for every call to the FastAPI backend.
// The session cookie is HttpOnly, so the browser sends it for us.

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      const d = body?.detail;
      // FastAPI validation errors (422) send a list of {loc, msg}
      if (Array.isArray(d)) message = d.map((e) => `${(e?.loc ?? []).filter((p: unknown) => p !== "body" && p !== "query").join(" ")}: ${e?.msg ?? e}`.replace(/^: /, "")).join("; ");
      else if (d) message = String(d);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};
