const TOKEN_KEY = "topstepbot_token";

const $ = (id) => document.getElementById(id);

let pollTimer = null;

async function api(path, options = {}) {
  const token = localStorage.getItem(TOKEN_KEY);
  const headers = { ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const res = await fetch(`/api/v1${path}`, { ...options, headers });
  if (res.status === 401) {
    logout();
    throw new Error("Unauthorized");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

function showApp() {
  $("login-screen").classList.add("hidden");
  $("app-screen").classList.remove("hidden");
  refresh();
  pollTimer = setInterval(refresh, 3000);
}

function logout() {
  localStorage.removeItem(TOKEN_KEY);
  clearInterval(pollTimer);
  $("app-screen").classList.add("hidden");
  $("login-screen").classList.remove("hidden");
}

function setBadge(state) {
  const el = $("state-badge");
  el.textContent = state || "unknown";
  el.className = "badge " + (state || "");
}

function setSignal(id, active) {
  const el = $(id);
  el.classList.toggle("active", !!active);
}

function renderTable(tbodyId, rows, emptyColspan, emptyText) {
  const tbody = $(tbodyId);
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="${emptyColspan}" class="muted">${emptyText}</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.join("");
}

async function refresh() {
  try {
    const [cfg, health, status, count, profit, trades, logs] = await Promise.all([
      api("/show_config"),
      api("/health"),
      api("/status"),
      api("/count"),
      api("/profit"),
      api("/trades"),
      api("/logs?limit=30"),
    ]);

    $("bot-name").textContent = cfg.bot_name;
    setBadge(health.bot_state);
    $("stat-pair").textContent = cfg.pair_whitelist?.[0] || health.last_signal?.pair || "—";
    $("stat-contract").textContent = health.last_signal?.contract || "—";
    $("stat-price").textContent = health.last_close?.toFixed?.(2) ?? health.last_close ?? "—";
    const pos = health.position_qty ?? 0;
    $("stat-position").textContent = pos === 0 ? "Flat" : `${pos > 0 ? "Long" : "Short"} ${Math.abs(pos)}`;
    $("stat-strategy").textContent = cfg.strategy;
    $("stat-mode").textContent = cfg.dry_run ? "Dry Run" : "Live";
    $("stat-count").textContent = `${count.current} / ${count.max}`;
    $("stat-profit").textContent = (profit.profit_closed_coin ?? 0).toFixed(2);
    $("last-loop").textContent = health.last_process || "—";

    const sig = health.last_signal || {};
    setSignal("sig-enter-long", sig.enter_long);
    setSignal("sig-enter-short", sig.enter_short);
    setSignal("sig-exit-long", sig.exit_long);
    setSignal("sig-exit-short", sig.exit_short);

    renderTable(
      "open-trades-body",
      status.map((t) =>
        `<tr>
          <td>${t.trade_id}</td><td>${t.pair}</td>
          <td>${t.is_short ? "Short" : "Long"}</td>
          <td>${t.amount}</td><td>${t.open_rate?.toFixed?.(2) ?? t.open_rate}</td>
          <td>${t.stake_amount}</td>
        </tr>`
      ),
      6,
      "No open trades"
    );

    renderTable(
      "trades-body",
      trades.slice(0, 20).map((t) =>
        `<tr>
          <td>${t.trade_id}</td><td>${t.pair}</td>
          <td>${t.is_short ? "Short" : "Long"}</td>
          <td>${t.open_rate?.toFixed?.(2) ?? "—"}</td>
          <td>${t.close_rate?.toFixed?.(2) ?? "—"}</td>
          <td>${(t.profit_abs ?? 0).toFixed(2)}</td>
          <td>${t.exit_reason ?? "—"}</td>
        </tr>`
      ),
      7,
      "No trades yet"
    );

    $("logs").textContent = (logs.logs || []).join("\n") || "No logs yet";
  } catch (e) {
    console.error(e);
  }
}

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = $("username").value;
  const password = $("password").value;
  const errEl = $("login-error");
  errEl.classList.add("hidden");
  try {
    const data = await api("/token/login", {
      method: "POST",
      body: { username, password },
    });
    localStorage.setItem(TOKEN_KEY, data.access_token);
    showApp();
  } catch (err) {
    errEl.textContent = err.message || "Login failed";
    errEl.classList.remove("hidden");
  }
});

$("btn-logout").addEventListener("click", logout);
$("btn-start").addEventListener("click", () => api("/start", { method: "POST" }).then(refresh));
$("btn-pause").addEventListener("click", () => api("/pause", { method: "POST" }).then(refresh));
$("btn-stopbuy").addEventListener("click", () => api("/stopbuy", { method: "POST" }).then(refresh));
$("btn-stop").addEventListener("click", () => api("/stop", { method: "POST" }).then(refresh));
$("btn-force-exit").addEventListener("click", () =>
  api("/forceexit", { method: "POST", body: { tradeid: "all" } }).then(refresh)
);
$("btn-force-enter").addEventListener("click", async () => {
  const cfg = await api("/show_config");
  const pair = cfg.pair_whitelist?.[0] || "MNQ";
  await api("/forceenter", { method: "POST", body: { pair, side: "long" } });
  refresh();
});

if (localStorage.getItem(TOKEN_KEY)) {
  showApp();
}
