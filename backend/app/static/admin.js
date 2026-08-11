const API = "/api/v1";
const BASE = window.location.origin;
let access = null;
let refresh = null;
let appsCache = [];

const $ = (id) => document.getElementById(id);

function saveTokens(a, r) {
  access = a;
  refresh = r;
  if (a && r) {
    localStorage.setItem("ls_access", a);
    localStorage.setItem("ls_refresh", r);
  }
}

function clearTokens() {
  access = null;
  refresh = null;
  localStorage.removeItem("ls_access");
  localStorage.removeItem("ls_refresh");
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function fmtDate(d) {
  if (!d) return "Lifetime";
  const dt = new Date(d);
  return isNaN(dt) ? String(d) : dt.toLocaleString();
}

function fmtExpiry(l) {
  // Timed key with no expiry stamped yet: the countdown starts on first use.
  if (!l.expires_at && l.validity_value && l.validity_unit)
    return "On first use";
  return fmtDate(l.expires_at);
}

function fmtKey(k) {
  return k ? k.replace(/-(?!\w{5}$)/g, "&#8209;") : "";
}

// ---------------------------------------------------------------- toasts
function toast(msg, kind = "ok", title = "") {
  const box = document.createElement("div");
  box.className = "toast " + kind;
  box.innerHTML = `<div class="tmsg">${title ? `<b>${esc(title)}</b>` : ""}<span>${esc(msg)}</span></div>`;
  $("toasts").appendChild(box);
  setTimeout(() => { box.style.opacity = "0"; box.style.transition = "opacity .3s"; setTimeout(() => box.remove(), 300); }, 5000);
}

// ---------------------------------------------------------------- modal
function modalConfirm({ title, body, okText = "Confirm", danger = false, input = null }) {
  return new Promise((resolve) => {
    const veil = document.createElement("div");
    veil.className = "modal-veil";
    veil.innerHTML = `
      <div class="modal">
        <h3>${esc(title)}</h3>
        <p>${body}</p>
        ${input ? `<input id="modal-input" type="${input.type || "text"}" placeholder="${esc(input.placeholder || "")}" style="width:100%;margin-top:12px" />` : ""}
        <div class="row">
          <button class="ghost" data-cancel>Cancel</button>
          <button class="${danger ? "danger" : ""}" data-ok>${esc(okText)}</button>
        </div>
      </div>`;
    veil.addEventListener("click", (e) => {
      if (e.target === veil) close(null);
    });
    veil.querySelector("[data-cancel]").addEventListener("click", () => close(null));
    veil.querySelector("[data-ok]").addEventListener("click", () => {
      const v = input ? (veil.querySelector("#modal-input").value || "").trim() : true;
      close(v);
    });
    function close(val) {
      veil.remove();
      resolve(val);
    }
    $("modal-root").appendChild(veil);
    if (input) veil.querySelector("#modal-input").focus();
  });
}

// ---------------------------------------------------------------- copy
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied to clipboard.");
  } catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
    toast("Copied to clipboard.");
  }
}

// ---------------------------------------------------------------- api
async function api(path, opts = {}) {
  opts.headers = opts.headers || {};
  opts.headers["Content-Type"] = "application/json";
  if (access) opts.headers["Authorization"] = "Bearer " + access;
  let resp = await fetch(API + path, opts);
  if (resp.status === 401 && access) {
    if (await tryRefresh()) {
      opts.headers["Authorization"] = "Bearer " + access;
      resp = await fetch(API + path, opts);
    }
  }
  const text = await resp.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
  if (!resp.ok) {
    const err = new Error((data && data.detail) || (data && data.message) || (resp.status === 404 ? "Not found" : resp.statusText || "Request failed"));
    err.status = resp.status;
    throw err;
  }
  return data;
}

async function tryRefresh() {
  if (!refresh) return false;
  try {
    const r = await fetch(API + "/admin/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!r.ok) { clearTokens(); showLogin(); return false; }
    const d = await r.json();
    saveTokens(d.access_token, d.refresh_token);
    return true;
  } catch (e) { return false; }
}

// ---------------------------------------------------------------- login / logout
function showLogin() {
  $("appView").classList.add("hidden");
  $("loginView").classList.remove("hidden");
}

$("login-btn").addEventListener("click", doLogin);
$("login-password").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
$("login-email").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });

async function doLogin() {
  const email = $("login-email").value.trim();
  const password = $("login-password").value;
  const btn = $("login-btn");
  if (!email || !password) { toast("Enter your email and password.", "error"); return; }
  btn.disabled = true; btn.textContent = "Signing in…";
  try {
    const d = await api("/admin/login", { method: "POST", body: JSON.stringify({ email, password }) });
    saveTokens(d.access_token, d.refresh_token);
    $("loginView").classList.add("hidden");
    $("appView").classList.remove("hidden");
    bootstrap();
  } catch (e) {
    toast(e.message, "error");
  } finally {
    btn.disabled = false; btn.textContent = "Sign in";
  }
}

$("logout-btn").addEventListener("click", async () => {
  try { if (refresh) await fetch(API + "/admin/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: refresh }) }); } catch (e) {}
  clearTokens();
  showLogin();
});

// Restore a persisted session on page load so refreshes don't re-login.
(function init() {
  const a = localStorage.getItem("ls_access");
  const r = localStorage.getItem("ls_refresh");
  if (a && r) {
    saveTokens(a, r);
    $("loginView").classList.add("hidden");
    $("appView").classList.remove("hidden");
    bootstrap();
  }
})();

// ---------------------------------------------------------------- navigation
const TITLES = {
  overview: ["Overview", "Live health of your license system"],
  apps: ["Applications", "Products your users can license"],
  licenses: ["Licenses", "Generate and manage license keys"],
  sessions: ["Sessions", "Devices currently using your keys"],
  developer: ["Developer", "Integrate your app in minutes"],
  audit: ["Audit log", "Full history of every action"],
  settings: ["Settings", "Account and security"],
};

function switchTab(tab) {
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  Object.keys(TITLES).forEach((t) => $("view-" + t).classList.toggle("hidden", t !== tab));
  $("page-title").textContent = TITLES[tab][0];
  $("page-crumb").textContent = "License Server / " + TITLES[tab][0];
  ({
    overview: renderOverview,
    apps: renderApps,
    licenses: renderLicenses,
    sessions: renderSessions,
    developer: renderDeveloper,
    audit: renderAudit,
    settings: renderSettings,
  })[tab]();
}

document.querySelectorAll("#nav button").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

async function bootstrap() {
  try {
    const me = await api("/admin/me");
    $("whoami").innerHTML = `${esc(me.email)}<small>Administrator</small>`;
  } catch (e) { /* token refresh handles it */ }
  renderOverview();
}

// ---------------------------------------------------------------- overview
async function renderOverview() {
  const el = $("view-overview");
  let s;
  try { s = await api("/admin/stats"); } catch (e) { el.innerHTML = `<div class="card"><p class="muted">${esc(e.message)}</p></div>`; return; }
  el.innerHTML = `
    <div class="grid4">
      <div class="stat"><div class="ic violet"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h7v7h-7z" opacity=".4"/></svg></div><div><div class="lab">Applications</div><div class="num">${s.apps}</div></div></div>
      <div class="stat"><div class="ic blue"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l8 3v6c0 5-3.5 9-8 11-4.5-2-8-6-8-11V5z"/><path d="M9 12l2 2 4-4"/></svg></div><div><div class="lab">Total licenses</div><div class="num">${s.licenses}</div></div></div>
      <div class="stat"><div class="ic green"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg></div><div><div class="lab">Active licenses</div><div class="num">${s.active_licenses}</div></div></div>
      <div class="stat"><div class="ic amber"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M8 21h8"/></svg></div><div><div class="lab">Live sessions</div><div class="num">${s.active_sessions}</div></div></div>
    </div>
    <div class="card">
      <div class="card-title">Quick start</div>
      <div class="card-sub">Three steps to license your product.</div>
      <table>
        <tbody>
          <tr><td style="width:34px;color:var(--accent2);font-weight:800">1</td><td><b>Create an application</b><div class="muted">Go to Applications and add your product.</div></td><td style="text-align:right"><button class="small ghost" onclick="switchTab('apps')">Open</button></td></tr>
          <tr><td style="color:var(--accent2);font-weight:800">2</td><td><b>Generate license keys</b><div class="muted">Create keys and hand them to your customers.</div></td><td style="text-align:right"><button class="small ghost" onclick="switchTab('licenses')">Open</button></td></tr>
          <tr><td style="color:var(--accent2);font-weight:800">3</td><td><b>Integrate your app</b><div class="muted">Copy ready-made code from the Developer tab.</div></td><td style="text-align:right"><button class="small ghost" onclick="switchTab('developer')">Open</button></td></tr>
        </tbody>
      </table>
    </div>`;
}

// ---------------------------------------------------------------- applications
async function renderApps() {
  let apps = [];
  try { apps = await api("/admin/apps"); appsCache = apps; } catch (e) { $("view-apps").innerHTML = `<div class="card"><p class="muted">${esc(e.message)}</p></div>`; return; }
  const rows = apps.map((a) => `
    <tr>
      <td><code class="mono">${esc(a.client_id)}</code> <button class="icon ghost small" title="Copy ID" onclick="copyText('${esc(a.client_id)}')"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 012-2h10"/></svg></button></td>
      <td><b>${esc(a.name)}</b></td>
      <td><span class="badge ${a.status}">${esc(a.status)}</span></td>
      <td>${esc(fmtDate(a.created_at))}</td>
      <td>
        <button class="small ghost" onclick="openDeveloper('${esc(a.id)}')">Integrate</button>
        <button class="small ghost" onclick="toggleApp('${esc(a.id)}')">${a.status === "active" ? "Disable" : "Enable"}</button>
        <button class="small ghost" onclick="regenerate('${esc(a.id)}')">New secret</button>
        <button class="small danger ghost" onclick="deleteApp('${esc(a.id)}')">Delete</button>
      </td>
    </tr>`).join("") || `<tr><td colspan="5"><div class="empty"><div class="big">&#128230;</div><p>No applications yet. Create your first one to start issuing keys.</p></div></td></tr>`;
  $("view-apps").innerHTML = `
    <div class="card">
      <div class="card-title">Create application</div>
      <div class="card-sub">Each application is a separate product with its own keys and client secret.</div>
      <div class="row">
        <input id="new-app-name" placeholder="Product name — e.g. My Game / Pro App" style="flex:1" />
        <button onclick="createApp()">Create</button>
      </div>
    </div>
    <div class="card">
      <div class="card-title">Applications <span class="pill">${apps.length}</span></div>
      <div class="table-wrap"><table>
        <thead><tr><th>Client ID</th><th>Name</th><th>Status</th><th>Created</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
    </div>`;
}

async function createApp() {
  const name = $("new-app-name").value.trim();
  if (!name) { toast("Enter a product name first.", "error"); return; }
  try {
    const app = await api("/admin/apps", { method: "POST", body: JSON.stringify({ name }) });
    sessionStorage.setItem("ls-secret-" + app.id, app.client_secret);
    $("new-app-name").value = "";
    renderApps();
    const copied = await modalConfirm({
      title: "Application created",
      body: `Client secret (shown once — store it now):<br><code class="mono" style="display:inline-block;margin-top:8px;max-width:100%">${esc(app.client_secret)}</code>`,
      okText: "Copy & done",
    });
    if (copied) copyText(app.client_secret);
  } catch (e) { toast(e.message, "error"); }
}

async function toggleApp(id) {
  try {
    const app = appsCache.find((a) => a.id === id);
    await api("/admin/apps/" + id, { method: "PATCH", body: JSON.stringify({ status: app.status === "active" ? "disabled" : "active" }) });
    toast(app.status === "active" ? "Application disabled — activation now rejected." : "Application enabled.");
    renderApps();
  } catch (e) { toast(e.message, "error"); }
}

async function regenerate(id) {
  const sure = await modalConfirm({ title: "Regenerate client secret?", body: "The old secret stops working immediately. Existing sessions stay valid until they expire.", okText: "Regenerate", danger: true });
  if (!sure) return;
  try {
    const app = await api("/admin/apps/" + id + "/regenerate-secret", { method: "POST", body: "{}" });
    sessionStorage.setItem("ls-secret-" + app.id, app.client_secret);
    const copy = await modalConfirm({ title: "New client secret", body: `This is shown once. Copy it now: <code class="mono">${esc(app.client_secret)}</code>`, okText: "Copy & done" });
    if (copy) copyText(app.client_secret);
  } catch (e) { toast(e.message, "error"); }
}

async function deleteApp(id) {
  const name = (appsCache.find((a) => a.id === id) || {}).name || id;
  const sure = await modalConfirm({ title: "Delete application?", body: `"${esc(name)}" will be deleted. Fails if it still has licenses. This cannot be undone.`, okText: "Delete", danger: true });
  if (!sure) return;
  try {
    await api("/admin/apps/" + id, { method: "DELETE" });
    toast("Application deleted.");
    renderApps();
  } catch (e) { toast(e.message, "error"); }
}

// ---------------------------------------------------------------- licenses
async function renderLicenses() {
  let apps = [];
  try { apps = await api("/admin/apps"); appsCache = apps; } catch (e) { $("view-licenses").innerHTML = `<div class="card"><p class="muted">${esc(e.message)}</p></div>`; return; }
  const options = apps.length ? apps.map((a) => `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join("")
    : `<option value="">No applications yet</option>`;
  const opts2 = apps.length ? apps.map((a) => `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join("")
    : `<option value="">No applications yet</option>`;
  $("view-licenses").innerHTML = `
    <div class="card">
      <div class="card-title">Generate licenses</div>
      <div class="card-sub">Create fresh keys for a product. Choose any duration down to minutes.</div>
      <div class="row grow">
        <div><label>Application</label><select id="lic-app" style="width:100%">${options}</select></div>
        <div><label>Duration</label>
          <div class="row" style="flex-wrap:nowrap">
            <input id="lic-dur" type="number" value="30" min="1" style="width:100px;flex:none" />
            <select id="lic-unit" style="flex:1">
              <option value="minutes">Minutes</option>
              <option value="hours">Hours</option>
              <option value="days" selected>Days</option>
              <option value="weeks">Weeks</option>
              <option value="months">Months</option>
              <option value="years">Years</option>
              <option value="lifetime">Lifetime</option>
            </select>
          </div>
        </div>
        <div><label>Count</label><input id="lic-count" type="number" value="1" min="1" max="100" style="width:100%" /></div>
        <div><label>Devices / key</label><input id="lic-max" type="number" value="1" min="1" max="100" style="width:100%" /></div>
      </div>
      <button style="margin-top:14px" onclick="generateLicenses()">Generate keys</button>
    </div>
    <div class="card">
      <div class="card-title">Licenses</div>
      <div class="row" style="margin-bottom:12px">
        <select id="list-app" style="max-width:180px">${opts2}</select>
        <select id="list-status" style="max-width:130px"><option value="">All statuses</option><option>active</option><option>revoked</option><option>banned</option><option>expired</option></select>
        <div class="search"><input id="list-search" placeholder="Search key…" /><button class="ghost" onclick="loadLicenses()">Refresh</button></div>
      </div>
      <div id="lic-table"></div>
    </div>`;
  loadLicenses();
}

async function loadLicenses() {
  const appId = $("list-app").value;
  const status = $("list-status").value;
  const search = $("list-search").value.trim();
  const q = new URLSearchParams({ app_id: appId });
  if (status) q.set("status", status);
  if (search) q.set("search", search);
  let rows = [];
  try { rows = await api("/admin/licenses?" + q.toString()); } catch (e) { $("lic-table").innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
  $("lic-table").innerHTML = rows.length ? `
    <div class="table-wrap"><table>
      <thead><tr><th>License key</th><th>Status</th><th>Expires</th><th>Device</th><th></th></tr></thead>
      <tbody>
      ${rows.map((l) => `
        <tr>
          <td><code class="mono">${fmtKey(esc(l.key))}</code> <button class="icon ghost small" title="Copy" onclick="copyText('${esc(l.key)}')"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 012-2h10"/></svg></button></td>
          <td><span class="badge ${esc(l.status)}">${esc(l.status)}</span>${l.banned_reason ? `<div class="tiny" style="color:var(--red);max-width:160px">${esc(l.banned_reason)}</div>` : ""}</td>
          <td>${esc(fmtExpiry(l))}</td>
          <td>${l.hwid_bound ? `<span class="badge bound">bound</span>` : `<span class="badge disabled">free</span>`}</td>
          <td>
            <button class="small ghost" onclick="openSessions('${esc(l.key)}')">Sessions</button>
            ${l.status === "active" ? `
              <button class="small ghost" onclick="revokeLic('${esc(l.key)}')">Revoke</button>
              <button class="small danger ghost" onclick="banLic('${esc(l.key)}')">Ban</button>
              <button class="small ghost" onclick="resetLic('${esc(l.key)}')">Reset</button>` : ""}
          </td>
        </tr>`).join("")}
      </tbody>
    </table></div>` : `<div class="empty"><div class="big">&#128273;</div><p>No licenses match. Generate some above.</p></div>`;
}

async function generateLicenses() {
  const appId = $("lic-app").value;
  if (!appId) { toast("Create an application first.", "error"); return; }
  const unit = $("lic-unit").value;
  const duration = unit === "lifetime" ? 0 : (parseInt($("lic-dur").value, 10) || 0);
  const count = parseInt($("lic-count").value, 10) || 1;
  const maxAct = parseInt($("lic-max").value, 10) || 1;
  if (!duration && unit !== "lifetime") { toast("Enter a duration greater than 0.", "error"); return; }
  try {
    const created = await api("/admin/licenses/for/" + appId, {
      method: "POST",
      body: JSON.stringify({ duration, unit, count, max_activations: maxAct }),
    });
    toast(`Generated ${created.length} key${created.length > 1 ? "s" : ""} (${unit === "lifetime" ? "lifetime" : duration + " " + unit}). Countdown starts on first activation.`, "ok");
    created.forEach((l) => copyKeyQueued(l.key));
    loadLicenses();
  } catch (e) { toast(e.message, "error"); }
}

let _copyQueue = [];
function copyKeyQueued(key) {
  _copyQueue.push(key);
  if (_copyQueue.length === 1) {
    setTimeout(async () => {
      const keys = _copyQueue.splice(0, _copyQueue.length);
      const all = keys.join("\n");
      await copyText(all);
      toast(`Copied ${keys.length} key${keys.length > 1 ? "s" : ""} to clipboard.`);
    }, 400);
  }
}

async function revokeLic(key) {
  const sure = await modalConfirm({ title: "Revoke license?", body: `Key <code class="mono">${esc(key)}</code> will stop working immediately for all devices.`, okText: "Revoke", danger: true });
  if (!sure) return;
  try { await api("/admin/licenses/revoke", { method: "POST", body: JSON.stringify({ key, reason: "revoked by admin" }) }); toast("License revoked.", "ok"); loadLicenses(); } catch (e) { toast(e.message, "error"); }
}

async function banLic(key) {
  const reason = await modalConfirm({ title: "Ban license", body: `Permanently ban <code class="mono">${esc(key)}</code>?`, okText: "Ban", danger: true, input: { type: "text", placeholder: "Reason (required)" } });
  if (!reason) return;
  try { await api("/admin/licenses/ban", { method: "POST", body: JSON.stringify({ key, reason }) }); toast("License banned.", "ok"); loadLicenses(); } catch (e) { toast(e.message, "error"); }
}

async function resetLic(key) {
  const sure = await modalConfirm({ title: "Reset license?", body: `Unbinds the device and kills all sessions for <code class="mono">${esc(key)}</code>.`, okText: "Reset", danger: true });
  if (!sure) return;
  try { await api("/admin/licenses/reset", { method: "POST", body: JSON.stringify({ key, reason: "" }) }); toast("License reset.", "ok"); loadLicenses(); } catch (e) { toast(e.message, "error"); }
}

// ---------------------------------------------------------------- sessions
function openSessions(key) {
  sessionStorage.setItem("ls-lic-key", key);
  switchTab("sessions");
}

async function renderSessions() {
  const prefill = sessionStorage.getItem("ls-lic-key") || "";
  $("view-sessions").innerHTML = `
    <div class="card">
      <div class="card-title">Device sessions</div>
      <div class="card-sub">Enter a license key to see every device session on it.</div>
      <div class="row">
        <input id="sess-key" placeholder="License key — e.g. ABCDE-FGHJK-…" style="flex:1;font-family:Consolas,monospace" value="${esc(prefill)}" />
        <button onclick="loadSessions()">View sessions</button>
      </div>
    </div>
    <div id="sess-result"></div>`;
  $("sess-key").addEventListener("keydown", (e) => { if (e.key === "Enter") loadSessions(); });
  if (prefill) loadSessions();
}

async function loadSessions() {
  const key = $("sess-key").value.trim();
  if (!key) { toast("Enter a license key.", "error"); return; }
  sessionStorage.setItem("ls-lic-key", key);
  $("sess-result").innerHTML = `<div class="card"><p class="muted">Loading…</p></div>`;
  let sessions;
  try { sessions = await api("/admin/sessions?license_key=" + encodeURIComponent(key)); } catch (e) { $("sess-result").innerHTML = `<div class="card"><p class="muted">${esc(e.message)}</p></div>`; return; }
  $("sess-result").innerHTML = `
    <div class="card">
      <div class="card-title">Sessions for <code class="mono">${fmtKey(esc(key))}</code></div>
      <div class="table-wrap"><table>
        <thead><tr><th>Created</th><th>Expires</th><th>Last seen</th><th>IP</th><th>Device</th><th>Status</th><th></th></tr></thead>
        <tbody>
        ${sessions.map((s) => `
          <tr>
            <td>${esc(fmtDate(s.created_at))}</td>
            <td>${esc(fmtDate(s.expires_at))}</td>
            <td>${esc(fmtDate(s.last_seen_at))}</td>
            <td><code class="mono">${esc(s.ip)}</code></td>
            <td class="muted" style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(s.user_agent)}">${esc(s.user_agent || "—")}</td>
            <td><span class="badge ${s.revoked ? "revoked" : "live"}">${s.revoked ? "revoked" : "live"}</span></td>
            <td>${s.revoked ? "" : `<button class="small danger ghost" onclick="revokeSession('${esc(s.id)}')">Revoke</button>`}</td>
          </tr>`).join("") || `<tr><td colspan="7"><div class="empty"><div class="big">&#128421;</div><p>No sessions for this key.</p></div></td></tr>`}
        </tbody>
      </table></div>
    </div>`;
}

async function revokeSession(id) {
  const sure = await modalConfirm({ title: "Revoke session?", body: "The device is logged out immediately.", okText: "Revoke", danger: true });
  if (!sure) return;
  try { await api("/admin/sessions/" + id + "/revoke", { method: "POST" }); toast("Session revoked.", "ok"); loadSessions(); } catch (e) { toast(e.message, "error"); }
}

// ---------------------------------------------------------------- developer
function appSecret(appId) {
  return sessionStorage.getItem("ls-secret-" + appId) || "";
}

async function renderDeveloper() {
  let apps = [];
  try { apps = await api("/admin/apps"); appsCache = apps; } catch (e) { $("view-developer").innerHTML = `<div class="card"><p class="muted">${esc(e.message)}</p></div>`; return; }
  const selectedId = sessionStorage.getItem("ls-dev-app") || (apps[0] && apps[0].id) || "";
  $("view-developer").innerHTML = `
    <div class="card">
      <div class="card-title">Integrate your application</div>
      <div class="card-sub">Pick a product, paste its secret, and copy ready-to-run code into your app.</div>
      <div class="row">
        <div style="min-width:220px">
          <label>Application</label>
          <select id="dev-app" style="width:100%">
            ${apps.length ? apps.map((a) => `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join("") : `<option value="">No applications yet</option>`}
          </select>
        </div>
        <div style="flex:1;min-width:260px">
          <label>Client secret</label>
          <div class="secret-box"><input id="dev-secret" type="password" style="flex:1;font-family:Consolas,monospace" placeholder="${appSecret(selectedId) ? "Saved in this browser" : "Paste your client secret (shown once at creation)"}" /><button class="ghost small" onclick="toggleSecret()">Show</button></div>
        </div>
      </div>
      <div id="dev-body" style="margin-top:6px"></div>
    </div>`;
  const sel = $("dev-app");
  sel.value = selectedId;
  if (appSecret(selectedId)) $("dev-secret").value = appSecret(selectedId);
  sel.addEventListener("change", () => {
    sessionStorage.setItem("ls-dev-app", sel.value);
    if (appSecret(sel.value)) $("dev-secret").value = appSecret(sel.value);
    renderSnippets();
  });
  $("dev-secret").addEventListener("input", () => {
    if (sel.value) sessionStorage.setItem("ls-secret-" + sel.value, $("dev-secret").value.trim());
    renderSnippets();
  });
  renderSnippets();
}

function toggleSecret() {
  const inp = $("dev-secret");
  inp.type = inp.type === "password" ? "text" : "password";
}

function currentDev() {
  const appId = $("dev-app").value;
  const app = appsCache.find((a) => a.id === appId) || {};
  return {
    appId,
    name: app.name || "",
    clientId: app.client_id || "",
    secret: $("dev-secret") ? $("dev-secret").value.trim() : "",
  };
}

function snippetVars() {
  const d = currentDev();
  const licKey = (sessionStorage.getItem("ls-test-key") || "").toUpperCase();
  return {
    base: BASE,
    api: BASE + API,
    appId: d.clientId || "APP_ID",
    secret: d.secret || "APP_SECRET",
    key: licKey || "ABCDE-FGHJK-MNPQR-STUVW-XYZ23",
    hwid: "HWID",
  };
}

const SNIPPETS = {
  python_sdk: `pip install licensify

from licensify import LicenseClient

client = LicenseClient(
    base_url="${"${base}"}",
    app_id="${"${appId}"}",
    app_secret="${"${secret}"}",
    timeout=15.0,
)

# ---- 1) Activate once (binds this device to the key) ----
session = client.activate(license_key="${"${key}"}", hwid=my_hwid())
save_token(session.session_token)

# ---- 2) Verify on every launch ----
# The token ROTATES on every verify call: use the returned one next time.
session = client.verify(current_token)
save_token(session.session_token)

# ---- 3) Release the device (optional, e.g. on clean exit) ----
client.deactivate(session.session_token)`,
  python_http: `import httpx

API = "${"${api}"}"
APP_ID = "${"${appId}"}"
APP_SECRET = "${"${secret}"}"

# Activate
r = httpx.post(f"{API}/auth/activate", json={
    "app_id": APP_ID, "app_secret": APP_SECRET,
    "key": "${"${key}"}", "hwid": my_hwid(),
}, timeout=15)
data = r.json()                       # 200 on success
session_token = data["session_token"]

# Verify (token rotates — store the returned token!)
r = httpx.post(f"{API}/auth/verify", json={
    "app_id": APP_ID, "session_token": session_token,
})
session_token = r.json()["session_token"]

# Deactivate
httpx.post(f"{API}/auth/deactivate", json={
    "app_id": APP_ID, "session_token": session_token,
})`,
  curl: `# Activate
curl -X POST "${"${api}"}/auth/activate" \\
  -H "Content-Type: application/json" \\
  -d '{"app_id":"${"${appId}"}","app_secret":"${"${secret}"}","key":"${"${key}"}","hwid":"HWID"}'

# Verify (rotates the token)
curl -X POST "${"${api}"}/auth/verify" \\
  -H "Content-Type: application/json" \\
  -d '{"app_id":"${"${appId}"}","session_token":"<session_token>"}'

# Deactivate
curl -X POST "${"${api}"}/auth/deactivate" \\
  -H "Content-Type: application/json" \\
  -d '{"app_id":"${"${appId}"}","session_token":"<session_token>"}'`,
  c: `/* C / C++ with libcurl. Build:  gcc app.c -o app -lcurl
   Pinning: set CURLOPT_CAINFO to a PEM bundle of YOUR server's CA.   */
#include <curl/curl.h>
#include <stdio.h>
#include <string.h>

static size_t on_body(void *p, size_t s, size_t n, void *o){
  size_t t = s * n;
  char *out = (char*)o;
  size_t have = strlen(out);
  memcpy(out + have, p, t);
  out[have + t] = '\0';
  return t;
}

static int post_json(const char *path, const char *json,
                     char *out, size_t outsz, long *code){
  char url[512];
  snprintf(url, sizeof url, "%s%s", "${"${api}"}", path);
  CURL *c = curl_easy_init();
  out[0] = '\0';
  curl_easy_setopt(c, CURLOPT_URL, url);
  curl_easy_setopt(c, CURLOPT_POST, 1L);
  curl_easy_setopt(c, CURLOPT_COPYPOSTFIELDS, json);
  curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, on_body);
  curl_easy_setopt(c, CURLOPT_WRITEDATA, out);
  /* curl_easy_setopt(c, CURLOPT_CAINFO, "server.pem");  // pin your cert */
  CURLcode rc = curl_easy_perform(c);
  curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, code);
  curl_easy_cleanup(c);
  return rc == CURLE_OK ? 0 : -1;
}

void activate(const char *key, const char *hwid){
  char json[512], out[1024]; long code = 0;
  snprintf(json, sizeof json,
    "{\\"app_id\\":\\"${"${appId}"}\\",\\"app_secret\\":\\"${"${secret}"}\\","
    "\\"key\\":\\"%s\\",\\"hwid\\":\\"%s\\"}", key, hwid);
  if (post_json("/auth/activate", json, out, sizeof out, &code) == 0 && code == 200)
    printf("session_token: %s\n", out);  /* parse JSON, store token */
}`,
  csharp: `using System;
using System.Net.Http;
using System.Text.Json;
using System.Threading.Tasks;

var http = new HttpClient { BaseAddress = new Uri("${"${base}"}") };

async Task<string> ActivateAsync(string key, string hwid) {
    var resp = await http.PostAsJsonAsync("/api/v1/auth/activate", new {
        app_id = "${"${appId}"}", app_secret = "${"${secret}"}",
        key = key, hwid = hwid
    });
    using var doc = JsonDocument.Parse(await resp.Content.ReadAsStringAsync());
    return doc.RootElement.GetProperty("session_token").GetString();
}

// Verify (token ROTATES each call) ------------------------------------
async Task<string> VerifyAsync(string sessionToken) {
    var resp = await http.PostAsJsonAsync("/api/v1/auth/verify", new {
        app_id = "${"${appId}"}", session_token = sessionToken
    });
    using var doc = JsonDocument.Parse(await resp.Content.ReadAsStringAsync());
    return doc.RootElement.GetProperty("session_token").GetString();
}

// Deactivate ----------------------------------------------------------
async Task DeactivateAsync(string sessionToken) {
    await http.PostAsJsonAsync("/api/v1/auth/deactivate", new {
        app_id = "${"${appId}"}", session_token = sessionToken
    });
}`,
  java: `import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

String API = "${"${api}"}";
String APP_ID = "${"${appId}"}";
String APP_SECRET = "${"${secret}"}";

static String post(String path, String json) throws Exception {
    HttpRequest req = HttpRequest.newBuilder(URI.create(API + path))
        .header("Content-Type", "application/json")
        .POST(HttpRequest.BodyPublishers.ofString(json)).build();
    return HttpClient.newHttpClient()
        .send(req, HttpResponse.BodyHandlers.ofString()).body();
}

// Activate -> parse JSON, take "session_token"
String activate = post("/auth/activate", String.format(
    "{\\"app_id\\":\\"%s\\",\\"app_secret\\":\\"%s\\",\\"key\\":\\"%s\\",\\"hwid\\":\\"%s\\"}",
    APP_ID, APP_SECRET, "KEY", "HWID"));

// Verify (rotates the token) -> use returned "session_token" next time
String verify = post("/auth/verify", String.format(
    "{\\"app_id\\":\\"%s\\",\\"session_token\\":\\"%s\\"}", APP_ID, sessionToken));`,
  go: `package main

import (
    "bytes"
    "encoding/json"
    "fmt"
    "net/http"
)

const (
    api      = "${"${api}"}"
    appID    = "${"${appId}"}"
    appSec   = "${"${secret}"}"
)

func post(path string, body map[string]string) (string, int) {
    b, _ := json.Marshal(body)
    resp, err := http.Post(api+path, "application/json", bytes.NewReader(b))
    if err != nil { panic(err) }
    defer resp.Body.Close()
    var out map[string]any
    json.NewDecoder(resp.Body).Decode(&out)
    token, _ := out["session_token"].(string)
    return token, resp.StatusCode
}

func activate(key, hwid string) string {
    token, code := post("/auth/activate", map[string]string{
        "app_id": appID, "app_secret": appSec, "key": key, "hwid": hwid,
    })
    if code != 200 { fmt.Println("activate failed:", code) }
    return token   // store; send to verify on next launch
}`,
  js: `const API = "${"${api}"}";
const APP_ID = "${"${appId}"}";
const APP_SECRET = "${"${secret}"}";

async function activate(key, hwid) {
  const r = await fetch(API + "/auth/activate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ app_id: APP_ID, app_secret: APP_SECRET, key, hwid }),
  });
  const d = await r.json();
  if (!r.ok) throw new Error(d.detail);
  return d.session_token;              // save this token
}

// Verify later — the server ROTATES the token on every call.
async function verify(sessionToken) {
  const r = await fetch(API + "/auth/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ app_id: APP_ID, session_token: sessionToken }),
  });
  const d = await r.json();
  if (!r.ok) throw new Error(d.detail);
  return d.session_token;              // use the returned token next time
}`,
  http_api: `BASE_URL   = ${"${base}"}

ACTIVATE    POST /api/v1/auth/activate
  body   { "app_id": APP_ID, "app_secret": APP_SECRET, "key": KEY, "hwid": HWID }
  200    { "ok": true, "session_token": "...", "expires_in": 86400, "expires_at": "..." }
  400    malformed key         401  bad app credentials
  403    banned / expired / max-activations / hwid-mismatch
  404    unknown key           429  rate limited (10/min/IP)

VERIFY      POST /api/v1/auth/verify        <- token ROTATES every call
  body   { "app_id": APP_ID, "session_token": TOKEN }
  200    { ..., "license_key": "KEY" }
  401    session expired / revoked / rotated
  403    key revoked, banned or expired

DEACTIVATE  POST /api/v1/auth/deactivate
  body   { "app_id": APP_ID, "session_token": TOKEN }
  204    ok       404   session already gone

RULES
  - Keys: XXXXX-XXXXX-XXXXX-XXXXX-XXXXX (uppercase)
  - hwid: any stable string >= 8 chars; server hashes it, never stores raw
  - First activation binds the HWID; a second device gets 403
  - The validity countdown starts on FIRST activation, not on generation
  - session_token rotates on every verify: always store the returned one
  - app_secret lives only in YOUR app; it can be extracted by reversers but
    grants no ability to mint or validate licenses
  - Identical protocol from Python, C/C++, C#, Java, Go, Rust, JS, ...`,
  hwid: `import hashlib, platform, uuid

def my_hwid():
    """Stable, per-machine fingerprint. Anything unique & stable works."""
    raw = platform.node() + "-" + str(uuid.getnode())
    return hashlib.sha256(raw.encode()).hexdigest()

# HWID requirements: at least 8 chars, never stored raw server-side
# (it is hashed with your SECRET_KEY before touching the database).
// C++/C# equivalent: hash MAC address + machine name with SHA-256.`,
};

function fillSnippet(tpl) {
  const v = snippetVars();
  return tpl
    .replace(/\$\{base\}/g, v.base)
    .replace(/\$\{api\}/g, v.api)
    .replace(/\$\{appId\}/g, v.appId)
    .replace(/\$\{secret\}/g, v.secret)
    .replace(/\$\{key\}/g, v.key)
    .replace(/\$\{hwid\}/g, v.hwid);
}

function highlight(code) {
  return esc(code)
    .replace(/#[^\n]*/g, (m) => `<span class="cm">${m}</span>`)
    .replace(/(pip install|from |import |def |class |async |await |const |let |var |return |if |else )/g, (m) => `<span class="k">${m}</span>`)
    .replace(/(httpx|fetch|LicenseClient|client|session|session_token|my_hwid)\./g, (m) => `<span class="f">${m}</span>`)
    .replace(/"([^"]*)"/g, (m) => `<span class="s">${m}</span>`)
    .replace(/(\$\{|\}|\d+\.\d+)/g, (m) => `<span class="n">${m}</span>`);
}

const LANG_LABELS = {
  python_sdk: "Python · SDK", python_http: "Python · HTTP", curl: "cURL",
  js: "JavaScript", c: "C / C++", csharp: "C#", java: "Java", go: "Go",
  http_api: "API Reference", hwid: "HWID helper",
};

async function renderSnippets() {
  const d = currentDev();
  const body = $("dev-body");
  if (!d.appId) {
    body.innerHTML = `<div class="empty" style="padding:24px"><div class="big">&#128736;</div><p>Create an application first, then come back here for integration code.</p></div>`;
    return;
  }
  body.innerHTML = `
    <div class="row" style="margin-top:14px">
      <div class="seg" id="dev-tabs">
        ${Object.entries(LANG_LABELS).map(([k, l]) => `<button data-lang="${k}"${k === "python_sdk" ? ' class="active"' : ""}>${l}</button>`).join("")}
      </div>
    </div>
    <div class="row" style="margin-top:12px">
      <div style="flex:1;min-width:240px">
        <label class="inline" style="margin:0">Test key</label>
        <input id="dev-test-key" style="width:100%;margin-top:4px;font-family:Consolas,monospace" placeholder="Paste a license key to prefill the snippets (optional)" value="${esc(snippetVars().key !== "ABCDE-FGHJK-MNPQR-STUVW-XYZ23" ? snippetVars().key : "")}" />
      </div>
      <div style="flex:1;min-width:240px">
        <label class="inline" style="margin:0">Test activation (live)</label>
        <div class="row"><button class="small" onclick="runTestActivation()" id="dev-test-btn">Run activation</button><span class="hint">Uses your app + secret + a random HWID against the live API.</span></div>
      </div>
    </div>
    <div id="dev-test-result"></div>
    <div id="dev-snippet"></div>`;

  $("dev-test-key").addEventListener("input", () => {
    sessionStorage.setItem("ls-test-key", $("dev-test-key").value.trim());
    showSnippet("python_sdk");
  });

  document.querySelectorAll("#dev-tabs button").forEach((b) => {
    b.addEventListener("click", () => {
      document.querySelectorAll("#dev-tabs button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      showSnippet(b.dataset.lang);
    });
  });
  showSnippet("python_sdk");
}

function showSnippet(lang) {
  const tpl = SNIPPETS[lang];
  if (!tpl) return;
  const filled = fillSnippet(tpl);
  const el = $("dev-snippet");
  if (!el) return;
  el.innerHTML = `
    <div class="code-head"><span class="lang">${esc(LANG_LABELS[lang] || lang.toUpperCase())}</span>
      <button class="ghost small" onclick="copyText(document.getElementById('dev-code').innerText)">Copy</button></div>
    <pre id="dev-code">${highlight(filled)}</pre>`;
}

async function runTestActivation() {
  const d = currentDev();
  if (!d.clientId) { toast("Create an application first.", "error"); return; }
  if (!d.secret) { toast("Enter the client secret in the field above.", "error"); return; }
  const key = (sessionStorage.getItem("ls-test-key") || "").trim().toUpperCase();
  if (!key) { toast("Paste a license key to test.", "error"); return; }
  const btn = $("dev-test-btn");
  const hwid = "dash-" + Math.random().toString(36).slice(2, 12);
  btn.disabled = true; btn.textContent = "Running…";
  $("dev-test-result").innerHTML = "";
  try {
    const r = await api("/auth/activate", { method: "POST", body: JSON.stringify({ app_id: d.clientId, app_secret: d.secret, key, hwid }) });
    const exp = r.expires_at ? new Date(r.expires_at).toLocaleString() : "—";
    $("dev-test-result").innerHTML = `<div class="okline" style="display:block">Activation OK — session token ready, expires ${esc(exp)}.</div>`;
    toast("Activation succeeded.", "ok", "Live test passed");
  } catch (e) {
    $("dev-test-result").innerHTML = `<div class="errline" style="display:block">${esc(e.message)}</div>`;
    toast(e.message, "error");
  } finally {
    btn.disabled = false; btn.textContent = "Run activation";
  }
}

function openDeveloper(appId) {
  sessionStorage.setItem("ls-dev-app", appId);
  switchTab("developer");
}

// ---------------------------------------------------------------- audit
async function renderAudit() {
  let entries = [];
  try { entries = await api("/admin/audit?limit=200"); } catch (e) { $("view-audit").innerHTML = `<div class="card"><p class="muted">${esc(e.message)}</p></div>`; return; }
  $("view-audit").innerHTML = `
    <div class="card">
      <div class="card-title">Audit log</div>
      <div class="card-sub">Every activation, verification, revoke and admin action, in order.</div>
      <div class="table-wrap"><table>
        <thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Target</th><th>IP</th><th>Details</th></tr></thead>
        <tbody>
        ${entries.map((e) => `
          <tr>
            <td style="white-space:nowrap">${esc(fmtDate(e.created_at))}</td>
            <td>${esc(e.actor_type)} <code class="mono">${esc(e.actor_id.slice(0, 8))}</code></td>
            <td><span class="badge ${e.action.includes("rejected") || e.action.includes("revoke") || e.action.includes("ban") ? "banned" : "ok"}">${esc(e.action)}</span></td>
            <td><code class="mono">${esc(e.target)}</code></td>
            <td><code class="mono">${esc(e.ip)}</code></td>
            <td class="muted" style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(e.details ? JSON.stringify(e.details) : "")}</td>
          </tr>`).join("") || `<tr><td colspan="6"><div class="empty"><div class="big">&#128203;</div><p>No events yet.</p></div></td></tr>`}
        </tbody>
      </table></div>
    </div>`;
}

// ---------------------------------------------------------------- settings
async function renderSettings() {
  $("view-settings").innerHTML = `
    <div class="card" style="max-width:520px">
      <div class="card-title">Change password</div>
      <div class="card-sub">Minimum 10 characters and at least one number. All admin sessions are signed out afterwards.</div>
      <label>Current password</label><input id="set-cur" type="password" style="width:100%" autocomplete="current-password" />
      <label>New password</label><input id="set-new" type="password" style="width:100%" autocomplete="new-password" />
      <label>Confirm new password</label><input id="set-new2" type="password" style="width:100%" autocomplete="new-password" />
      <button style="margin-top:16px" onclick="changePassword()">Update password</button>
    </div>
    <div class="card" style="max-width:520px">
      <div class="card-title">Session rules</div>
      <div class="kv">
        <dt>Session lifetime</dt><dd>24 hours, refreshed on every verify</dd>
        <dt>Key rotation</dt><dd>Session tokens rotate on every verification</dd>
        <dt>HWID binding</dt><dd>First device wins; stored hashed, never raw</dd>
        <dt>Activation limit</dt><dd>Configurable per key at generation</dd>
        <dt>Expiry</dt><dd>Countdown starts on first activation, not on generation</dd>
      </div>
    </div>`;
}

async function changePassword() {
  const cur = $("set-cur").value;
  const n1 = $("set-new").value;
  const n2 = $("set-new2").value;
  if (n1 !== n2) { toast("New passwords do not match.", "error"); return; }
  try {
    await api("/admin/change-password", { method: "POST", body: JSON.stringify({ current_password: cur, new_password: n1 }) });
    toast("Password updated. Sign in again.", "ok");
    setTimeout(() => { clearTokens(); showLogin(); }, 900);
  } catch (e) { toast(e.message, "error"); }
}
