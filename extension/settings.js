/* Shared by background, popup and options. */
const RFQ_DEFAULTS = { backendUrl: "http://localhost:8000", frontendUrl: "http://localhost:5173", apiKey: "" };

async function rfqSettings() {
  const stored = await chrome.storage.sync.get(RFQ_DEFAULTS);
  return { ...RFQ_DEFAULTS, ...stored, backendUrl: stored.backendUrl.replace(/\/$/, ""), frontendUrl: stored.frontendUrl.replace(/\/$/, "") };
}

async function rfqFetch(path, init = {}) {
  const s = await rfqSettings();
  const headers = { "X-API-Key": s.apiKey, ...(init.body ? { "Content-Type": "application/json" } : {}), ...(init.headers || {}) };
  const res = await fetch(`${s.backendUrl}${path}`, { ...init, headers });
  const text = await res.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    const detail = body && body.detail ? (typeof body.detail === "string" ? body.detail : body.detail.message || JSON.stringify(body.detail)) : `HTTP ${res.status}`;
    const err = new Error(res.status === 401 ? "Wrong API key. Set it in the extension options." : detail);
    err.status = res.status;
    throw err;
  }
  return body;
}
