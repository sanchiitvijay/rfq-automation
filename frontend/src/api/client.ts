/** Thin typed fetch wrapper. All requests carry the API key; errors become ApiError with the server's detail. */
const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "http://localhost:8000";
const KEY = (import.meta.env.VITE_API_KEY as string | undefined) ?? "";
const USER_KEY = "rfq.user";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body: unknown,
  ) {
    super(message);
  }
}

export function getUser(): string {
  try {
    return localStorage.getItem(USER_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setUser(name: string): void {
  try {
    localStorage.setItem(USER_KEY, name);
  } catch {
    /* storage blocked: the name just is not remembered */
  }
}

function detailOf(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object" && "message" in d) return String((d as { message: unknown }).message);
    if (Array.isArray(d)) return d.map((x) => (x && typeof x === "object" && "msg" in x ? String(x.msg) : String(x))).join("; ");
  }
  return fallback;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-API-Key", KEY);
  const user = getUser();
  if (user) headers.set("X-User", user);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Cannot reach the RFQ backend. Is it running on " + BASE + "?", null);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) throw new ApiError(res.status, detailOf(body, `Request failed (${res.status})`), body);
  return body as T;
}

/** URL for links/EventSource, which cannot send headers. */
export function apiUrl(path: string, params: Record<string, string | number> = {}): string {
  const q = new URLSearchParams({ key: KEY, ...Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])) });
  return `${BASE}${path}?${q.toString()}`;
}
