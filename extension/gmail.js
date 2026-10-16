/*
 * Content script on mail.google.com. On request from the popup it reads the email that is open:
 *   1. the raw message ("Show original"), which keeps Excel attachments (preferred);
 *   2. otherwise the visible text from the page (attachments not included).
 * Gmail's markup changes over time, so every selector lives in SELECTORS below.
 */
(() => {
  if (window.__rfqAgentLoaded) return;
  window.__rfqAgentLoaded = true;

  const SELECTORS = {
    openMessage: "div.adn.ads[data-message-id]", // expanded messages in a conversation
    anyMessage: "[data-message-id]",
    legacyMessage: "[data-legacy-message-id]",
    subject: "h2.hP",
    sender: ".gD", // has the email in its "email" attribute
    body: ".a3s",
    rawText: "#raw_message_text, pre",
  };
  const MAX_RAW_BYTES = 15 * 1024 * 1024;

  function accountIndex() {
    const m = location.pathname.match(/\/mail\/u\/(\d+)/);
    return m ? m[1] : "0";
  }

  /** The open message: the last expanded one in the conversation. */
  function openMessageElement() {
    const expanded = document.querySelectorAll(SELECTORS.openMessage);
    if (expanded.length) return expanded[expanded.length - 1];
    const any = document.querySelectorAll(SELECTORS.anyMessage);
    return any.length ? any[any.length - 1] : null;
  }

  function messageId(el) {
    const id = (el && el.getAttribute("data-message-id")) || "";
    if (id) return id.replace(/^#/, ""); // e.g. "msg-f:1812345678901234567"
    const legacy = document.querySelector(SELECTORS.legacyMessage);
    const hex = legacy && legacy.getAttribute("data-legacy-message-id");
    return hex ? `msg-f:${BigInt("0x" + hex).toString()}` : "";
  }

  /** Gmail's session key ("ik"), needed for the Show original URL. */
  function sessionKey() {
    const html = document.documentElement.innerHTML;
    const patterns = [/GLOBALS=\[(?:[^,\]]*,){9}"([0-9a-f]{6,14})"/, /"ik":"([0-9a-f]{6,14})"/, /[?&]ik=([0-9a-f]{6,14})/];
    for (const re of patterns) {
      const m = html.match(re);
      if (m) return m[1];
    }
    return "";
  }

  /** True only for a raw message: it must start with a header line (an HTML page never does). */
  function looksLikeMime(text) {
    const head = text.trimStart().slice(0, 8000);
    if (head.startsWith("<")) return false;
    return /^[\w-]+:[ \t]/.test(head) && /^(from|subject|date|message-id|mime-version):/im.test(head);
  }

  function toBase64(text) {
    const bytes = new TextEncoder().encode(text);
    let binary = "";
    for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(binary);
  }

  async function fetchRaw(msgId) {
    const ik = sessionKey();
    if (!msgId || !ik) throw new Error("could not identify the open message");
    const url = `/mail/u/${accountIndex()}/?ik=${ik}&view=om&permmsgid=${encodeURIComponent(msgId)}`;
    const res = await fetch(url, { credentials: "include" });
    if (!res.ok) throw new Error(`Show original returned ${res.status}`);
    let text = await res.text();
    if (!looksLikeMime(text)) {
      const doc = new DOMParser().parseFromString(text, "text/html");
      const pre = doc.querySelector(SELECTORS.rawText);
      text = pre ? pre.textContent || "" : "";
    }
    if (!looksLikeMime(text)) throw new Error("Show original did not contain a message");
    if (text.length > MAX_RAW_BYTES) throw new Error("the email is larger than 15 MB");
    return text.replace(/\r?\n/g, "\r\n");
  }

  function visibleText(el) {
    const scope = el || document;
    const subject = (document.querySelector(SELECTORS.subject) || {}).innerText || "";
    const senderEl = scope.querySelector(SELECTORS.sender);
    const name = senderEl ? senderEl.getAttribute("name") || senderEl.innerText : "";
    const address = senderEl ? senderEl.getAttribute("email") || "" : "";
    const bodyEl = scope.querySelector(SELECTORS.body);
    return {
      subject: subject.trim(),
      sender: address ? `${name} <${address}>` : name,
      body_text: bodyEl ? bodyEl.innerText.trim() : "",
    };
  }

  async function extract() {
    const el = openMessageElement();
    const id = messageId(el);
    const visible = visibleText(el);
    if (!el && !visible.body_text) {
      return { ok: false, error: "No email is open. Open the RFQ email in Gmail, then click the extension again." };
    }
    const result = { ok: true, source: "extension", gmail_msg_id: id || null, ...visible, extract_warnings: [] };
    try {
      result.raw_eml_b64 = toBase64(await fetchRaw(id));
    } catch (e) {
      if (!visible.body_text) return { ok: false, error: `Could not read the email: ${e.message}` };
      result.extract_warnings.push(`Only the visible text was sent (attachments not included): ${e.message}.`);
    }
    return result;
  }

  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    if (msg && msg.type === "rfq:extract") {
      extract().then(reply, (e) => reply({ ok: false, error: String(e && e.message ? e.message : e) }));
      return true; // async reply
    }
    return false;
  });
})();
