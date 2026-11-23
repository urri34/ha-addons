// Common helpers. All paths are relative so they work inside HA Ingress.
async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-CSRF": window.CSRF},
    body: JSON.stringify(body),
  };
  const base = document.baseURI.replace(/[^/]*$/, "");
  const r = await fetch(new URL(path, base), opt);
  if (r.status === 401) { location.reload(); throw new Error(T["js.session_expired"]); }
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}
function setText(id, t) { const e = document.getElementById(id); if (e) e.textContent = t == null ? "" : t; }
function esc(s) { return String(s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c])); }
function copyText(id) { return copyString(document.getElementById(id).textContent); }
// Copy to clipboard. Without HTTPS (direct port access) navigator.clipboard does not exist:
// a temporary textarea is used instead.
async function copyString(t) {
  try { if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(t); return true; } } catch (e) {}
  const ta = document.createElement("textarea");
  ta.value = t; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  let ok = false; try { ok = document.execCommand("copy"); } catch (e) {}
  ta.remove(); return ok;
}

// claude.ai login block (_login.html)
function initLogin() {
  if (!document.getElementById("lg-start")) return;
  const LS = {starting: T["js.lg_starting"], waiting_code: T["js.lg_waiting_code"], checking: T["js.lg_checking"], done: T["js.lg_done"], error: T["js.lg_error"], idle: ""};
  let timer = null, watching = false, loginUrl = "";
  async function poll() {
    const d = await api("api/login");
    // A login finished during another visit must not be shown again
    if (d.state === "done" && !watching) d.state = "idle";
    document.getElementById("lg-box").hidden = d.state === "idle";
    setText("lg-state", (LS[d.state] || d.state) + (d.message && d.state !== "done" ? " " + d.message : ""));
    const showLink = !!d.url && d.state === "waiting_code";
    document.getElementById("lg-link").hidden = !showLink;
    if (showLink) { document.getElementById("lg-open").href = d.url; loginUrl = d.url; }
    document.getElementById("lg-codebox").hidden = d.state !== "waiting_code";
    setText("lg-out", d.output);
    document.getElementById("lg-start").disabled = ["starting", "waiting_code", "checking"].includes(d.state);
    document.getElementById("lg-cancel").disabled = !["starting", "waiting_code"].includes(d.state);
    if (d.state === "done") { clearInterval(timer); setTimeout(() => location.reload(), 1500); }
    if (d.state === "error" || d.state === "idle") clearInterval(timer);
  }
  function startPoll() { watching = true; clearInterval(timer); timer = setInterval(poll, 1500); poll(); }
  document.getElementById("lg-start").onclick = async () => { await api("api/login/start", {}); startPoll(); };
  document.getElementById("lg-cancel").onclick = async () => { await api("api/login/cancel", {}); poll(); };
  const send = async () => {
    const code = document.getElementById("lg-code").value.trim();
    if (!code) return;
    await api("api/login/code", {code}); document.getElementById("lg-code").value = ""; startPoll();
  };
  document.getElementById("lg-send").onclick = send;
  document.getElementById("lg-copy").onclick = async () => {
    const ok = await copyString(loginUrl);
    setText("lg-copied", ok ? T["js.copied"] : T["js.copy_failed"]);
    setTimeout(() => setText("lg-copied", ""), 2500);
  };
  document.getElementById("lg-code").addEventListener("keydown", e => { if (e.key === "Enter") send(); });
  poll().then(() => { if (!document.getElementById("lg-box").hidden) startPoll(); });
}
