const API = "/api/v1";
let access = null;
let refresh = null;
let appsCache = [];

const $ = (id) => document.getElementById(id);

function showMsg(el, text, kind = "error") {
  el.textContent = text;
  el.className = "msg " + kind;
  el.style.display = "block";
  setTimeout(() => { el.style.display = "none"; }, 5000);
}

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
  const data = text ? JSON.parse(text) : null;
  if (!resp.ok) {
    const err = new Error((data && data.detail) || resp.statusText);
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
    if (!r.ok) { access = null; refresh = null; showLogin(); return false; }
    const d = await r.json();
    access = d.access_token;
    refresh = d.refresh_token;
    return true;
  } catch (e) { return false; }
}

// ---------------------------------------------------------------- login
function showLogin() {
  $("appView").classList.add("hidden");
  $("loginView").classList.remove("hidden");
}

$("login-btn").addEventListener("click", async () => {
  const email = $("login-email").value.trim();
  const password = $("login-password").value;
  try {
    const d = await api("/admin/login", { method: "POST", body: JSON.stringify({ email, password }) });
    access = d.access_token;
    refresh = d.refresh_token;
    $("loginView").classList.add("hidden");
    $("appView").classList.remove("hidden");
    bootstrap();
  } catch (e) {
    showMsg($("login-err"), e.message);
  }
});

$("logout-btn").addEventListener("click", async () => {
  try { if (refresh) await fetch(API + "/admin/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: refresh }) }); } catch (e) {}
  access = null; refresh = null;
  showLogin();
});

// ---------------------------------------------------------------- tabs
document.querySelectorAll(".nav button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    ["stats", "apps", "licenses", "sessions", "audit"].forEach((t) =>
      $("view-" + t).classList.toggle("hidden", t !== btn.dataset.tab)
    );
    if (btn.dataset.tab === "stats") renderStats();
    if (btn.dataset.tab === "apps") renderApps();
    if (btn.dataset.tab === "audit") renderAudit();
  });
});

async function bootstrap() {
  const me = await api("/admin/me");
  $("whoami").textContent = me.email;
  renderStats();
}

// ---------------------------------------------------------------- overview
async function renderStats() {
  try {
    const s = await api("/admin/stats");
    $("view-stats").innerHTML = `
      <div class="row">
        <div class="card" style="flex:1"><h2>Applications</h2><div style="font-size:26px;font-weight:700">${s.apps}</div></div>
        <div class="card" style="flex:1"><h2>Licenses</h2><div style="font-size:26px;font-weight:700">${s.licenses}</div></div>
        <div class="card" style="flex:1"><h2>Active licenses</h2><div style="font-size:26px;font-weight:700">${s.active_licenses}</div></div>
        <div class="card" style="flex:1"><h2>Live sessions</h2><div style="font-size:26px;font-weight:700">${s.active_sessions}</div></div>
      </div>`;
  } catch (e) { $("view-stats").innerHTML = `<div class="msg error">${e.message}</div>`; }
}

// ---------------------------------------------------------------- apps
async function renderApps() {
  let apps = [];
  try {
    apps = await api("/admin/apps");
    appsCache = apps;
  } catch (e) { $("view-apps").innerHTML = `<div class="msg error">${e.message}</div>`; return; }
  const rows = apps.map((a) => `
    <tr>
      <td><code>${a.client_id}</code></td>
      <td>${a.name}</td>
      <td><span class="badge b-${a.status}">${a.status}</span></td>
      <td>
        <button class="small ghost" onclick="toggleApp('${a.id}')">${a.status === "active" ? "Disable" : "Enable"}</button>
        <button class="small ghost" onclick="regenerate('${a.id}')">New secret</button>
        <button class="small danger" onclick="deleteApp('${a.id}')">Delete</button>
      </td>
    </tr>`).join("");
  $("view-apps").innerHTML = `
    <div class="card">
      <h2>Create application</h2>
      <div class="row">
        <input id="new-app-name" placeholder="App name" style="flex:1" />
        <button onclick="createApp()">Create</button>
      </div>
      <div class="msg ok" id="app-msg"></div>
    </div>
    <div class="card">
      <h2>Applications</h2>
      <table><thead><tr><th>Client ID</th><th>Name</th><th>Status</th><th></th></tr></thead>
      <tbody>${rows || `<tr><td colspan="4" class="muted">No applications yet.</td></tr>`}</tbody></table>
    </div>`;
}

async function createApp() {
  const name = $("new-app-name").value.trim();
  if (!name) return;
  try {
    const app = await api("/admin/apps", { method: "POST", body: JSON.stringify({ name }) });
    showMsg($("app-msg"), `Created "${app.name}". SECRET (shown once): ${app.client_secret}`, "ok");
    $("new-app-name").value = "";
    renderApps();
  } catch (e) { showMsg($("app-msg"), e.message); }
}

async function toggleApp(id) {
  try {
    const app = appsCache.find((a) => a.id === id);
    await api("/admin/apps/" + id, { method: "PATCH", body: JSON.stringify({ status: app.status === "active" ? "disabled" : "active" }) });
    renderApps();
  } catch (e) { alert(e.message); }
}

async function regenerate(id) {
  if (!confirm("Regenerate client secret? The old one stops working immediately.")) return;
  try {
    const app = await api("/admin/apps/" + id + "/regenerate-secret", { method: "POST", body: "{}" });
    alert("New client secret (shown once): " + app.client_secret);
    renderApps();
  } catch (e) { alert(e.message); }
}

async function deleteApp(id) {
  if (!confirm("Delete this application? Refused if it still has licenses.")) return;
  try {
    await api("/admin/apps/" + id, { method: "DELETE" });
    renderApps();
  } catch (e) { alert(e.message); }
}

// ---------------------------------------------------------------- licenses
async function renderLicenses() {
  let apps = [];
  try { apps = await api("/admin/apps"); appsCache = apps; } catch (e) { $("view-licenses").innerHTML = `<div class="msg error">${e.message}</div>`; return; }
  const options = apps.map((a) => `<option value="${a.id}">${a.name}</option>`).join("");
  $("view-licenses").innerHTML = `
    <div class="card">
      <h2>Generate licenses</h2>
      <div class="row">
        <label>App <select id="lic-app">${options}</select></label>
        <label>Validity <select id="lic-days"><option value="30">30 days</option><option value="90">90 days</option><option value="365">1 year</option><option value="0">Lifetime</option></select></label>
        <label>Count <input id="lic-count" type="number" value="1" min="1" max="100" style="width:80px" /></label>
        <label>Devices/key <input id="lic-max" type="number" value="1" min="1" max="100" style="width:80px" /></label>
      </div>
      <button onclick="generateLicenses()">Generate</button>
      <div class="msg ok" id="lic-msg"></div>
    </div>
    <div class="card">
      <h2>Licenses</h2>
      <div class="row">
        <select id="list-app">${options}</select>
        <select id="list-status"><option value="">All</option><option>active</option><option>revoked</option><option>banned</option><option>expired</option></select>
        <input id="list-search" placeholder="search key / device" style="flex:1" />
        <button class="ghost" onclick="loadLicenses()">Refresh</button>
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
  try { rows = await api("/admin/licenses?" + q.toString()); } catch (e) { $("lic-table").innerHTML = `<div class="msg error">${e.message}</div>`; return; }
  $("lic-table").innerHTML = `
    <table>
      <thead><tr><th>Key</th><th>Status</th><th>Expires</th><th>Device</th><th></th></tr></thead>
      <tbody>
      ${rows.map((l) => `
        <tr>
          <td><code>${l.key}</code></td>
          <td><span class="badge b-${l.status}">${l.status}</span>${l.banned_reason ? `<br><span class="muted">${l.banned_reason}</span>` : ""}</td>
          <td>${l.expires_at ? new Date(l.expires_at).toLocaleString() : "Lifetime"}</td>
          <td>${l.hwid_bound ? "bound" : "free"}</td>
          <td class="row">
            <button class="small ghost" onclick="openSessions('${l.key}')">Sessions</button>
            ${l.status === "active" ? `<button class="small ghost" onclick="revokeLic('${l.key}')">Revoke</button>
            <button class="small danger" onclick="banLic('${l.key}')">Ban</button>
            <button class="small ghost" onclick="resetLic('${l.key}')">Reset</button>` : ""}
          </td>
        </tr>`).join("") || `<tr><td colspan="5" class="muted">No licenses.</td></tr>`}
      </tbody>
    </table>`;
}

async function generateLicenses() {
  const appId = $("lic-app").value;
  const days = parseInt($("lic-days").value, 10);
  const count = parseInt($("lic-count").value, 10);
  const maxAct = parseInt($("lic-max").value, 10);
  try {
    const created = await api("/admin/licenses/for/" + appId, {
      method: "POST",
      body: JSON.stringify({ days, count, max_activations: maxAct }),
    });
    showMsg($("lic-msg"), "Generated " + created.length + " key(s): " + created.map((l) => l.key).join(", "), "ok");
    loadLicenses();
  } catch (e) { showMsg($("lic-msg"), e.message); }
}

async function revokeLic(key) {
  try { await api("/admin/licenses/revoke", { method: "POST", body: JSON.stringify({ key, reason: "revoked by admin" }) }); loadLicenses(); } catch (e) { alert(e.message); }
}
async function banLic(key) {
  const reason = prompt("Ban reason:"); if (!reason) return;
  try { await api("/admin/licenses/ban", { method: "POST", body: JSON.stringify({ key, reason }) }); loadLicenses(); } catch (e) { alert(e.message); }
}
async function resetLic(key) {
  if (!confirm("Reset this key? Unbinds the device and kills all its sessions.")) return;
  try { await api("/admin/licenses/reset", { method: "POST", body: JSON.stringify({ key, reason: "" }) }); loadLicenses(); } catch (e) { alert(e.message); }
}

// ---------------------------------------------------------------- sessions
async function openSessions(key) {
  document.querySelectorAll(".nav button").forEach((b) => b.classList.remove("active"));
  document.querySelector('.nav button[data-tab="sessions"]').classList.add("active");
  ["stats","apps","licenses","audit"].forEach((t) => $("view-" + t).classList.add("hidden"));
  $("view-sessions").classList.remove("hidden");
  $("view-sessions").innerHTML = `<div class="card"><h2>Loading sessions for <code>${key}</code>…</h2></div>`;
  try {
    const sessions = await api("/admin/sessions?license_key=" + encodeURIComponent(key));
    $("view-sessions").innerHTML = `
      <div class="card">
        <h2>Sessions for <code>${key}</code></h2>
        <table>
          <thead><tr><th>Created</th><th>Expires</th><th>Last seen</th><th>IP</th><th>Status</th><th></th></tr></thead>
          <tbody>
          ${sessions.map((s) => `
            <tr>
              <td>${new Date(s.created_at).toLocaleString()}</td>
              <td>${new Date(s.expires_at).toLocaleString()}</td>
              <td>${new Date(s.last_seen_at).toLocaleString()}</td>
              <td><code>${s.ip}</code></td>
              <td><span class="badge b-${s.revoked ? "revoked" : "ok"}">${s.revoked ? "revoked" : "live"}</span></td>
              <td>${s.revoked ? "" : `<button class="small danger" onclick="revokeSession('${s.id}')">Revoke</button>`}</td>
            </tr>`).join("") || `<tr><td colspan="6" class="muted">No sessions.</td></tr>`}
          </tbody>
        </table>
        <button class="ghost small" style="margin-top:10px" onclick="renderLicenses()">Back</button>
      </div>`;
  } catch (e) { $("view-sessions").innerHTML = `<div class="msg error">${e.message}</div>`; }
}

async function revokeSession(id) {
  try { await api("/admin/sessions/" + id + "/revoke", { method: "POST" }); openSessions(sessionStorage.getItem("lic-key") || ""); } catch (e) { alert(e.message); }
}

// ---------------------------------------------------------------- audit
async function renderAudit() {
  let entries = [];
  try { entries = await api("/admin/audit?limit=200"); } catch (e) { $("view-audit").innerHTML = `<div class="msg error">${e.message}</div>`; return; }
  $("view-audit").innerHTML = `
    <div class="card">
      <h2>Audit log</h2>
      <table>
        <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Target</th><th>IP</th><th>Details</th></tr></thead>
        <tbody>
        ${entries.map((e) => `
          <tr>
            <td>${new Date(e.created_at).toLocaleString()}</td>
            <td>${e.actor_type} <code>${e.actor_id.slice(0, 8)}</code></td>
            <td><code>${e.action}</code></td>
            <td>${e.target}</td>
            <td><code>${e.ip}</code></td>
            <td class="muted">${e.details ? JSON.stringify(e.details) : ""}</td>
          </tr>`).join("") || `<tr><td colspan="6" class="muted">No events yet.</td></tr>`}
        </tbody>
      </table>
    </div>`;
}
