/* Service worker: submits the extracted email to the backend (one retry on network errors). */
importScripts("settings.js");

async function submit(payload) {
  let lastError;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      return await rfqFetch("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
    } catch (e) {
      lastError = e;
      if (e.status) break; // the server answered: retrying will not help
      await new Promise((r) => setTimeout(r, 1500));
    }
  }
  if (!lastError.status) {
    const s = await rfqSettings();
    throw new Error(`Cannot reach the RFQ backend at ${s.backendUrl}. Is it running?`);
  }
  throw lastError;
}

async function remember(job, subject) {
  const { recent = [] } = await chrome.storage.local.get("recent");
  const next = [{ id: job.job_id, subject, at: Date.now() }, ...recent.filter((r) => r.id !== job.job_id)].slice(0, 8);
  await chrome.storage.local.set({ recent: next });
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg && msg.type === "rfq:submit") {
    (async () => {
      const job = await submit(msg.payload);
      await remember(job, msg.payload.subject || "(no subject)");
      const s = await rfqSettings();
      await chrome.tabs.create({ url: `${s.frontendUrl}/jobs/${job.job_id}` });
      return { ok: true, job };
    })().then(reply, (e) => reply({ ok: false, error: e.message }));
    return true;
  }
  return false;
});

chrome.runtime.onInstalled.addListener(async ({ reason }) => {
  if (reason === "install") {
    const s = await rfqSettings();
    if (!s.apiKey) chrome.runtime.openOptionsPage();
  }
});
