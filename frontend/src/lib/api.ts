// Typed fetch client with JWT auth header, consistent error extraction and pagination.

const BASE = "/api";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

export function getToken(): string | null {
  return localStorage.getItem("evalforge_token");
}

function headers(json = true): HeadersInit {
  const h: Record<string, string> = {};
  const token = getToken();
  if (token) h["Authorization"] = `Bearer ${token}`;
  if (json) h["Content-Type"] = "application/json";
  return h;
}

export async function request<T>(
  method: string,
  path: string,
  opts: { json?: unknown; form?: FormData; raw?: boolean } = {},
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      method,
      headers: headers(!opts.form),
      body: opts.form ? opts.form : opts.json !== undefined ? JSON.stringify(opts.json) : undefined,
    });
  } catch {
    throw new ApiError(0, "Cannot reach the EvalForge API. Is the backend running on port 8000?");
  }
  if (res.status === 204) return undefined as T;
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    /* empty body */
  }
  if (!res.ok) {
    if (res.status === 401) {
      // token invalid/expired → force re-login
      localStorage.removeItem("evalforge_token");
      localStorage.removeItem("evalforge_user");
    }
    const detail = (data as { detail?: unknown })?.detail ?? `HTTP ${res.status}`;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, json?: unknown) => request<T>("POST", path, { json }),
  put: <T>(path: string, json?: unknown) => request<T>("PUT", path, { json }),
  patch: <T>(path: string, json?: unknown) => request<T>("PATCH", path, { json }),
  del: <T>(path: string) => request<T>("DELETE", path),
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, { form }),
  /** Authenticated binary download (keeps the Authorization header). */
  getRawBlob: async (path: string): Promise<{ blob: Blob; disposition: string | null }> => {
    let res: Response;
    try {
      res = await fetch(BASE + path, { headers: headers(false) });
    } catch {
      throw new ApiError(0, "Cannot reach the EvalForge API. Is the backend running on port 8000?");
    }
    if (!res.ok) {
      let detail: unknown = `HTTP ${res.status}`;
      try { detail = (await res.json())?.detail ?? detail; } catch { /* keep */ }
      if (res.status === 401) {
        localStorage.removeItem("evalforge_token");
        localStorage.removeItem("evalforge_user");
      }
      throw new ApiError(res.status, detail);
    }
    return { blob: await res.blob(), disposition: res.headers.get("content-disposition") };
  },
};

export function pageParams(page: number, pageSize: number, extra: Record<string, string | number | boolean | undefined> = {}) {
  const p = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  for (const [k, v] of Object.entries(extra)) {
    if (v !== undefined && v !== "") p.set(k, String(v));
  }
  return `?${p.toString()}`;
}
