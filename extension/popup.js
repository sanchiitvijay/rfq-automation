const LABEL = { queued: "Queued", running: "Processing", needs_review: "Needs review", ready: "Reviewed", sending: "Sending", sent: "Sent", failed: "Failed" };
const $ = (id) => document.getElementById(id);

function show(text, kind = "") {
  const el = $("msg");
  el.hidden = false;
  el.className = `msg ${kind}`;
  el.textContent = text;
}

async function extractFromTab(tab) {
  const ask = () => chrome.tabs.sendMessage(tab.id, { type: "rfq:extract" });
  try {
    return await ask();
  } catch {
    // tab was open before the extension was installed: inject the content script, then ask again
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["gmail.js"] });
    return await ask();
  }
}

async function send() {
  const button = $("send");
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url || !tab.url.startsWith("https://mail.google.com/")) {
    show("Open the RFQ email in Gmail first, then click this button.", "warn");
    return;
  }
  button.disabled = true;
  button.textContent = "Reading the email…";
  try {
    const email = await extractFromTab(tab);
    if (!email || !email.ok) throw new Error((email && email.error) || "Could not read the email.");
    button.textContent = "Sending…";
    const { ok, ...payload } = email;
    const result = await chrome.runtime.sendMessage({ type: "rfq:submit", payload });
    if (!result || !result.ok) throw new Error((result && result.error) || "The backend did not accept the email.");
    const note = email.extract_warnings && email.extract_warnings.length ? ` ${email.extract_warnings[0]}` : "";
    show(result.job.created ? `Sent. The RFQ is being prepared.${note}` : "This email was already sent; opening the existing request.", note ? "warn" : "ok");
    await renderRecent();
  } catch (e) {
    show(e.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "Send this email to the RFQ Agent";
  }
}

async function renderRecent() {
  const { recent = [] } = await chrome.storage.local.get("recent");
  if (!recent.length) return;
  const s = await rfqSettings();
  const list = $("recent");
  list.replaceChildren();
  for (const r of recent) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = `${s.frontendUrl}/jobs/${r.id}`;
    a.target = "_blank";
    a.textContent = r.subject;
    const status = document.createElement("span");
    status.className = "status";
    status.textContent = "…";
    li.append(a, status);
    list.append(li);
    rfqFetch(`/api/jobs/${r.id}`)
      .then((job) => {
        status.textContent = job.status === "running" && job.eta_seconds ? `${LABEL[job.status]} · ~${Math.max(5, job.eta_seconds)} s` : LABEL[job.status] || job.status;
      })
      .catch(() => (status.textContent = "unavailable"));
  }
}

$("send").addEventListener("click", send);
$("options").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});
rfqSettings().then((s) => {
  if (!s.apiKey) show("Set the API key in Settings before sending.", "warn");
});
renderRecent();
