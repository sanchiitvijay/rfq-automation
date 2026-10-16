const fields = ["backendUrl", "frontendUrl", "apiKey"];
const $ = (id) => document.getElementById(id);

function show(text, kind = "") {
  const el = $("msg");
  el.hidden = false;
  el.className = `msg ${kind}`;
  el.textContent = text;
}

async function load() {
  const s = await rfqSettings();
  for (const f of fields) $(f).value = s[f];
}

async function save() {
  const values = Object.fromEntries(fields.map((f) => [f, $(f).value.trim()]));
  for (const key of ["backendUrl", "frontendUrl"]) {
    try {
      const u = new URL(values[key]);
      if (!/^https?:$/.test(u.protocol)) throw new Error();
    } catch {
      show(`${key === "backendUrl" ? "Backend" : "Web app"} URL is not a valid http(s) address.`, "error");
      return false;
    }
  }
  const origin = new URL(values.backendUrl).origin + "/*";
  if (!/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?\/\*$/.test(origin)) {
    const granted = await chrome.permissions.request({ origins: [origin] });
    if (!granted) {
      show("Permission to contact the backend was not granted.", "error");
      return false;
    }
  }
  await chrome.storage.sync.set(values);
  show("Saved.", "ok");
  return true;
}

$("save").addEventListener("click", save);
$("test").addEventListener("click", async () => {
  if (!(await save())) return;
  try {
    const h = await rfqFetch("/api/health");
    await rfqFetch("/api/jobs?limit=1"); // checks the API key too
    show(`Connected. Database ${h.db}, queue ${h.queue}, ferguson.com lookup ${h.chrome} (${h.mode}).`, "ok");
  } catch (e) {
    show(e.message, "error");
  }
});
load();
