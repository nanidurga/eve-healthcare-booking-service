/* EVE Diagnostics — demo front end.
 *
 * Plain JavaScript, no build step: FastAPI serves this directory as-is. Every
 * request goes through api(), which also writes it to the traffic console so
 * a reviewer can see exactly what the backend was asked and what it answered.
 */

const API = "/api/v1";
const $ = (sel, root = document) => root.querySelector(sel);
const store = store_();

const state = {
  token: store.get("eve.token"),
  user: store.get("eve.user"),
  view: "centres",
  city: null,
  centreId: null,
  bookingFilter: "",
  lab: { ref: "", eventId: newEventId(), deliveries: [] },
};

/* ---------------------------------------------------------------- utils */

function store_() {
  // localStorage can throw (private mode, blocked storage); the app still works without it.
  return {
    get(key) { try { return JSON.parse(localStorage.getItem(key)); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* ignore */ } },
    del(key) { try { localStorage.removeItem(key); } catch { /* ignore */ } },
  };
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

const rupees = (amount) => "₹" + Number(amount).toLocaleString("en-IN", { minimumFractionDigits: 2 });

const when = (iso) => new Date(iso).toLocaleString(undefined, {
  weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit",
});

function newEventId() {
  return "evt_" + Math.random().toString(16).slice(2, 10);
}

function toast(message, kind = "info") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.innerHTML = message;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), kind === "error" ? 6000 : 3500);
}

function toastError(res) {
  const err = res.data && res.data.error;
  if (!err) return toast(`Request failed (HTTP ${res.status})`, "error");
  let msg = esc(err.message);
  if (err.details && err.details.fields) {
    msg += "<br>" + err.details.fields.map((f) => `${esc(f.field)}: ${esc(f.message)}`).join("<br>");
  }
  toast(`${msg}<br><code>${esc(err.code)} · HTTP ${res.status}</code>`, "error");
}

/* Payments made with mode=async are remembered per user, so the webhook lab
 * has provider references to deliver events for. The API has no endpoint that
 * lists payments, and a real provider would know these references anyway. */
const paymentsKey = () => `eve.payments.${state.user && state.user.id}`;
const savedPayments = () => store.get(paymentsKey()) || [];
function savePayment(payment) {
  const list = savedPayments().filter((p) => p.provider_reference !== payment.provider_reference);
  list.unshift({
    provider_reference: payment.provider_reference,
    booking_id: payment.booking_id,
    amount: payment.amount,
    label: `${payment.booking.test.code} · ${payment.booking.centre.name.replace("EVE Diagnostics - ", "")}`,
  });
  store.set(paymentsKey(), list.slice(0, 20));
}

/* ------------------------------------------------------------------ api */

async function api(method, path, body, { auth = true, quiet = false } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth && state.token) headers.Authorization = "Bearer " + state.token;

  const started = performance.now();
  let status = 0;
  let data = null;
  try {
    const resp = await fetch(API + path, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
    });
    status = resp.status;
    const text = await resp.text();
    data = text ? JSON.parse(text) : null;
  } catch (e) {
    data = { error: { code: "network_error", message: "Could not reach the API. Is the server running?" } };
  }
  const ms = Math.round(performance.now() - started);
  logRequest({ method, path, body, status, data, ms });

  const res = { ok: status >= 200 && status < 300, status, data };
  if (status === 401 && auth && state.token) {
    signOut();
    toast("Your session expired. Please sign in again.", "error");
  } else if (!res.ok && !quiet) {
    toastError(res);
  }
  return res;
}

function logRequest({ method, path, body, status, data, ms }) {
  const log = $("#log");
  $(".log-empty", log)?.remove();
  const li = document.createElement("li");
  const redacted = body && body.password ? { ...body, password: "••••••••" } : body;
  const shownData = data && data.access_token
    ? { ...data, access_token: data.access_token.slice(0, 16) + "…" }
    : data;
  li.innerHTML = `
    <details ${log.children.length === 0 ? "open" : ""}>
      <summary>
        <span class="method">${esc(method)}</span>
        <span class="path" title="${esc(API + path)}">${esc(path)}</span>
        <span><span class="status st-${String(status)[0]}">${status || "ERR"}</span> <span class="ms">${ms}ms</span></span>
      </summary>
      <pre>${redacted !== undefined ? `<span class="lbl">request</span>${esc(JSON.stringify(redacted, null, 2))}\n` : ""}<span class="lbl">response</span>${esc(JSON.stringify(shownData, null, 2))}</pre>
    </details>`;
  // Keep only the newest entry expanded.
  log.querySelectorAll("details[open]").forEach((d) => d.removeAttribute("open"));
  li.querySelector("details").open = true;
  log.prepend(li);
  while (log.children.length > 60) log.lastElementChild.remove();
}

/* ---------------------------------------------------------------- shell */

function renderShell() {
  const signedIn = Boolean(state.token);
  $("#tabs").hidden = !signedIn;
  document.querySelectorAll("#tabs button").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === state.view);
  });
  $("#session").innerHTML = signedIn
    ? `<span>Signed in as <strong>${esc(state.user.full_name)}</strong></span>
       <button class="btn secondary small" id="signout">Sign out</button>`
    : `<a class="muted" href="/docs" target="_blank" rel="noopener">API docs ↗</a>`;
  $("#signout")?.addEventListener("click", signOut);
}

function go(view) {
  state.view = view;
  render();
}

function render() {
  renderShell();
  if (!state.token) return renderAuth();
  ({ centres: renderCentres, bookings: renderBookings, webhook: renderWebhook })[state.view]();
}

function signOut() {
  state.token = null;
  state.user = null;
  store.del("eve.token");
  store.del("eve.user");
  render();
}

/* ----------------------------------------------------------------- auth */

function renderAuth(mode = "login") {
  $("#main").innerHTML = `
    <div class="auth-wrap">
      <section>
        <h1>Book a diagnostic test, then watch the backend handle it.</h1>
        <p class="lede">This page is a thin client over the EVE Diagnostics API. Everything it does is a
          real HTTP call, shown live in the panel on the right.</p>
        <ol class="flow">
          <li><div><strong>Pick a centre and a test.</strong> <span class="muted">Price lives on the offering, so the same test costs different amounts at different centres.</span></div></li>
          <li><div><strong>Book it.</strong> <span class="muted">The booking starts in <code>PENDING</code> with the price snapshotted.</span></div></li>
          <li><div><strong>Pay.</strong> <span class="muted">Settle instantly, force a decline, or leave it pending for the provider.</span></div></li>
          <li><div><strong>Fire webhooks.</strong> <span class="muted">Deliver the same event three times and see it applied exactly once.</span></div></li>
        </ol>
      </section>
      <section class="card">
        <div class="seg">
          <button data-mode="login" class="${mode === "login" ? "active" : ""}">Sign in</button>
          <button data-mode="signup" class="${mode === "signup" ? "active" : ""}">Create account</button>
        </div>
        <form id="auth-form" class="stack">
          ${mode === "signup" ? `
            <div><label for="full_name">Full name</label><input id="full_name" required maxlength="120" autocomplete="name"></div>
            <div><label for="phone">Phone <span class="muted">(optional)</span></label><input id="phone" maxlength="20" autocomplete="tel"></div>` : ""}
          <div><label for="email">Email</label><input id="email" type="email" required autocomplete="email"
            value="${mode === "login" ? "asha@example.com" : ""}"></div>
          <div><label for="password">Password</label><input id="password" type="password" required
            minlength="${mode === "signup" ? 8 : 1}" autocomplete="${mode === "signup" ? "new-password" : "current-password"}"
            value="${mode === "login" ? "password123" : ""}"></div>
          <button class="btn" type="submit" style="width:100%;justify-content:center">
            ${mode === "login" ? "Sign in" : "Create account"}</button>
          ${mode === "login" ? `<p class="demo-hint">Prefilled with the seeded demo patient. Run <code>python -m scripts.seed</code> if sign-in fails.</p>` : ""}
        </form>
      </section>
    </div>`;

  document.querySelectorAll(".seg button").forEach((b) =>
    b.addEventListener("click", () => renderAuth(b.dataset.mode)));

  $("#auth-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("button[type=submit]", e.target);
    btn.disabled = true;
    const body = { email: $("#email").value.trim(), password: $("#password").value };
    if (mode === "signup") {
      body.full_name = $("#full_name").value.trim();
      const phone = $("#phone").value.trim();
      if (phone) body.phone = phone;
    }
    const res = await api("POST", `/auth/${mode}`, body, { auth: false });
    btn.disabled = false;
    if (!res.ok) return;
    state.token = res.data.access_token;
    state.user = res.data.user;
    store.set("eve.token", state.token);
    store.set("eve.user", state.user);
    toast(`Welcome, ${esc(state.user.full_name)}.`);
    go("centres");
  });
}

/* -------------------------------------------------------------- centres */

async function renderCentres() {
  $("#main").innerHTML = `
    <h1>Book a test</h1>
    <p class="lede">Choose a centre to see what it offers. Tip: <strong>LFT at Banjara Hills</strong> is priced
      <code>999.13</code> — amounts ending in <code>.13</code> are always declined by the simulated gateway.</p>
    <div class="chips" id="cities"></div>
    <div class="centres" id="centres"><div class="card empty">Loading centres…</div></div>
    <div id="offerings"></div>`;

  const all = await api("GET", "/centres?limit=100", undefined, { auth: false });
  if (!all.ok) return;
  const cities = [...new Set(all.data.items.map((c) => c.city))].sort();

  const drawCentres = () => {
    $("#cities").innerHTML = [null, ...cities].map((c) =>
      `<button class="chip ${state.city === c ? "active" : ""}" data-city="${esc(c ?? "")}">${esc(c ?? "All cities")}</button>`).join("");
    document.querySelectorAll("#cities .chip").forEach((b) => b.addEventListener("click", () => {
      state.city = b.dataset.city || null;
      drawCentres();
    }));
    const shown = all.data.items.filter((c) => !state.city || c.city === state.city);
    $("#centres").innerHTML = shown.length ? shown.map((c) => `
      <button class="card centre ${c.id === state.centreId ? "selected" : ""}" data-id="${c.id}">
        <div class="city">${esc(c.city)}</div>
        <h3>${esc(c.name)}</h3>
        <div class="muted" style="font-size:13px">${esc(c.address)}</div>
      </button>`).join("")
      : `<div class="card empty">No centres yet. Run <code>python -m scripts.seed</code>.</div>`;
    document.querySelectorAll(".centre").forEach((el) => el.addEventListener("click", () => {
      state.centreId = Number(el.dataset.id);
      drawCentres();
      renderOfferings();
    }));
  };
  drawCentres();
  if (state.centreId) renderOfferings();
}

function defaultSlot() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(9, 30, 0, 0);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function renderOfferings() {
  const box = $("#offerings");
  box.innerHTML = `<div class="card offerings empty">Loading tests…</div>`;
  const res = await api("GET", `/centres/${state.centreId}`, undefined, { auth: false });
  if (!res.ok) return (box.innerHTML = "");
  const centre = res.data;
  box.innerHTML = `
    <section class="card offerings">
      <div class="row"><h2>${esc(centre.name)}</h2><span class="spacer"></span>
        <span class="muted" style="font-size:13px">${esc(centre.phone || "")}</span></div>
      <div style="margin-top:10px">
      ${centre.tests.map((o) => `
        <div class="offering">
          <span class="code">${esc(o.test.code)}</span>
          <div>
            <strong>${esc(o.test.name)}</strong>
            <div class="muted" style="font-size:13px">${esc(o.test.description || "")}</div>
            ${o.test.preparation ? `<div class="prep">Preparation: ${esc(o.test.preparation)}</div>` : ""}
            ${o.price.endsWith(".13") ? `<div class="flag">Will be declined by the simulated gateway</div>` : ""}
          </div>
          <span class="price">${rupees(o.price)}</span>
          <button class="btn small" data-offering="${o.id}" ${o.is_active ? "" : "disabled"}>Book</button>
        </div>
        <div id="book-${o.id}"></div>`).join("") || `<p class="muted">This centre offers no tests yet.</p>`}
      </div>
    </section>`;

  box.querySelectorAll("[data-offering]").forEach((b) => b.addEventListener("click", () => {
    const id = b.dataset.offering;
    box.querySelectorAll("[id^=book-]").forEach((el) => (el.innerHTML = ""));
    $(`#book-${id}`).innerHTML = `
      <form class="book-form">
        <div><label for="slot-${id}">Appointment (your local time)</label>
          <input type="datetime-local" id="slot-${id}" value="${defaultSlot()}" required></div>
        <button class="btn" type="submit">Confirm booking</button>
        <button class="btn secondary" type="button" data-close>Cancel</button>
      </form>`;
    const form = $(`#book-${id} form`);
    $("[data-close]", form).addEventListener("click", () => ($(`#book-${id}`).innerHTML = ""));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const local = $(`#slot-${id}`).value;
      const res = await api("POST", "/bookings", {
        centre_test_id: Number(id),
        // toISOString() is UTC with a "Z" suffix — timezone-aware, as the API requires.
        appointment_at: new Date(local).toISOString(),
      });
      if (!res.ok) return;
      toast(`Booking #${res.data.id} created — status <strong>${res.data.status}</strong>. Pay for it next.`);
      state.bookingFilter = "";
      go("bookings");
    });
  }));
}

/* ------------------------------------------------------------- bookings */

function stateMachine(current) {
  const node = (name, x, y) => `
    <g class="node ${name} ${name === current ? "on" : ""}">
      <rect x="${x}" y="${y}" width="104" height="30" rx="15"/>
      <text x="${x + 52}" y="${y + 19}" text-anchor="middle">${name}</text>
    </g>`;
  return `
    <svg class="sm" viewBox="0 0 560 142" role="img" aria-label="Booking state: ${current}">
      <defs><marker id="arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
        <path d="M0,0 L8,4 L0,8 z"/></marker></defs>
      <path class="edge" d="M108 60 L222 25" marker-end="url(#arr)"/>
      <text class="edge-label" x="140" y="32">paid</text>
      <path class="edge" d="M108 82 L222 115" marker-end="url(#arr)"/>
      <text class="edge-label" x="135" y="120">declined</text>
      <path class="edge" d="M240 101 Q 170 92 112 76" marker-end="url(#arr)"/>
      <text class="edge-label" x="182" y="87">retry</text>
      <path class="edge" d="M112 71 L446 71" marker-end="url(#arr)" stroke-dasharray="4 3"/>
      <text class="edge-label" x="300" y="66">cancel</text>
      <path class="edge" d="M330 25 L448 60" marker-end="url(#arr)"/>
      <text class="edge-label" x="392" y="34">cancel</text>
      <path class="edge" d="M330 115 L448 82" marker-end="url(#arr)"/>
      <text class="edge-label" x="392" y="114">cancel</text>
      ${node("PENDING", 4, 56)}
      ${node("CONFIRMED", 226, 8)}
      ${node("FAILED", 226, 102)}
      ${node("CANCELLED", 450, 56)}
    </svg>`;
}

function bookingCard(b) {
  const payable = b.status === "PENDING" || b.status === "FAILED";
  const pending = savedPayments().find((p) => p.booking_id === b.id);
  return `
    <article class="card booking" id="booking-${b.id}">
      <div>
        <div class="row"><span class="code">${esc(b.test.code)}</span><h3>${esc(b.test.name)}</h3></div>
        <div class="booking-meta">#${b.id} · ${esc(b.centre.name)} · ${when(b.appointment_at)} ·
          <span class="mono">${rupees(b.amount)}</span></div>
      </div>
      <span class="badge s-${b.status}">${b.status}</span>
      ${stateMachine(b.status)}
      ${b.cancellation_reason ? `<div class="note muted">Cancelled: ${esc(b.cancellation_reason)}</div>` : ""}
      ${b.status === "PENDING" && pending ? `<div class="note muted">An async payment may be waiting for its webhook —
        <a href="#" data-lab="${esc(pending.provider_reference)}">settle it in the webhook lab</a>.</div>` : ""}
      <div class="booking-actions">
        <button class="btn small" data-pay="sync" ${payable ? "" : "disabled"}>${b.status === "FAILED" ? "Retry payment" : "Pay now"}</button>
        <button class="btn warn small" data-pay="fail" ${payable ? "" : "disabled"} title="force_status: FAILED">Pay, force decline</button>
        <button class="btn secondary small" data-pay="async" ${payable ? "" : "disabled"} title="mode: async — settles by webhook">Pay via webhook</button>
        <span class="spacer"></span>
        <button class="btn danger small" data-cancel ${b.status === "CANCELLED" ? "disabled" : ""}>Cancel booking</button>
      </div>
    </article>`;
}

async function renderBookings() {
  const filters = ["", "PENDING", "CONFIRMED", "FAILED", "CANCELLED"];
  $("#main").innerHTML = `
    <h1>My bookings</h1>
    <p class="lede">Each booking moves through an explicit state machine. Anything not drawn below is rejected
      with <code>409</code> — try cancelling twice, or paying a confirmed booking.</p>
    <div class="chips">${filters.map((f) =>
      `<button class="chip ${state.bookingFilter === f ? "active" : ""}" data-f="${f}">${f || "All"}</button>`).join("")}</div>
    <div class="bookings" id="bookings"><div class="card empty">Loading…</div></div>`;

  document.querySelectorAll(".chips .chip").forEach((b) => b.addEventListener("click", () => {
    state.bookingFilter = b.dataset.f;
    renderBookings();
  }));

  const qs = state.bookingFilter ? `&status=${state.bookingFilter}` : "";
  const res = await api("GET", `/bookings?limit=50${qs}`);
  if (!res.ok) return;
  const list = $("#bookings");
  if (!res.data.items.length) {
    list.innerHTML = `<div class="card empty">No bookings here yet.
      <p><button class="btn" id="to-centres">Book a test</button></p></div>`;
    $("#to-centres").addEventListener("click", () => go("centres"));
    return;
  }
  list.innerHTML = res.data.items.map(bookingCard).join("");
  res.data.items.forEach((b) => wireBooking(b));
}

function wireBooking(b) {
  const card = $(`#booking-${b.id}`);
  const replace = (booking) => {
    card.outerHTML = bookingCard(booking);
    wireBooking(booking);
  };

  card.querySelectorAll("[data-pay]").forEach((btn) => btn.addEventListener("click", async () => {
    const kind = btn.dataset.pay;
    const body = { booking_id: b.id };
    if (kind === "fail") body.force_status = "FAILED";
    if (kind === "async") body.mode = "async";
    card.querySelectorAll("button").forEach((x) => (x.disabled = true));
    const res = await api("POST", "/payments", body);
    if (!res.ok) return replace(b);
    const p = res.data;
    if (kind === "async") {
      savePayment(p);
      toast(`Payment <code>${esc(p.provider_reference)}</code> is PENDING. Settle it from the webhook lab.`);
    } else if (p.status === "SUCCESS") {
      toast(`Payment succeeded — booking #${b.id} is <strong>CONFIRMED</strong>.`);
    } else {
      toast(`Payment declined: ${esc(p.failure_reason || "unknown reason")}. You can retry.`, "error");
    }
    replace(p.booking);
  }));

  card.querySelector("[data-cancel]").addEventListener("click", async () => {
    const res = await api("POST", `/bookings/${b.id}/cancel`, { reason: "Cancelled from the demo UI" });
    if (!res.ok) return;
    toast(`Booking #${b.id} cancelled.`);
    replace(res.data);
  });

  card.querySelector("[data-lab]")?.addEventListener("click", (e) => {
    e.preventDefault();
    openLab(e.target.dataset.lab);
  });
}

/* --------------------------------------------------------- webhook lab */

function openLab(ref) {
  state.lab = { ref, eventId: newEventId(), deliveries: [] };
  go("webhook");
}

const OUTCOME_TEXT = {
  applied: "Payment and booking updated.",
  duplicate: "Already processed this event_id — nothing changed.",
  ignored_terminal_payment: "Payment had already settled — ignored.",
  booking_not_updatable: "Payment recorded, but the booking may not change (e.g. cancelled).",
};

function renderWebhook() {
  const saved = savedPayments();
  const lab = state.lab;
  if (!lab.ref && saved.length) lab.ref = saved[0].provider_reference;
  const current = saved.find((p) => p.provider_reference === lab.ref);

  $("#main").innerHTML = `
    <h1>Webhook lab</h1>
    <p class="lede">Play the payment provider. Deliver the same event more than once, deliver events out of order,
      or deliver one for a booking you've already cancelled — the endpoint should answer <code>200</code> every time
      and change state at most once.</p>

    <div class="lab">
      <section class="card stack">
        <h2>Compose an event</h2>
        ${saved.length ? "" : `<p class="explain">No async payments yet. On <a href="#" data-go="bookings">My bookings</a>,
          use <strong>Pay via webhook</strong> to create one that waits for this endpoint.</p>`}
        <div><label for="ref">Payment (provider_reference)</label>
          <select id="ref">
            ${saved.map((p) => `<option value="${esc(p.provider_reference)}" ${p.provider_reference === lab.ref ? "selected" : ""}>
              #${p.booking_id} ${esc(p.label)} — ${esc(p.provider_reference)}</option>`).join("")}
            <option value="__custom" ${saved.length && !current ? "selected" : ""}>Enter manually…</option>
          </select></div>
        <div id="custom-ref" ${saved.length && current ? "hidden" : ""}>
          <label for="ref-input">provider_reference</label>
          <input id="ref-input" class="mono" placeholder="pay_…" value="${current ? "" : esc(lab.ref)}"></div>
        <div class="field-row">
          <div><label for="evt">event_id</label>
            <div class="row" style="flex-wrap:nowrap"><input id="evt" class="mono" value="${esc(lab.eventId)}">
              <button class="btn secondary small" id="new-evt" title="Generate a new event_id">↻</button></div></div>
          <div><label for="wh-status">status</label>
            <select id="wh-status"><option>SUCCESS</option><option>FAILED</option></select></div>
        </div>
        <div class="field-row">
          <div><label for="amt">amount <span class="muted">(optional, must match)</span></label>
            <input id="amt" class="mono" value="${current ? esc(current.amount) : ""}"></div>
          <div><label for="reason">failure_reason</label><input id="reason" placeholder="insufficient_funds"></div>
        </div>
        <div class="row">
          <button class="btn" id="deliver">Deliver once</button>
          <button class="btn secondary" id="deliver3">Deliver same event ×3</button>
        </div>
      </section>

      <section class="card stack">
        <div class="row"><h2>Deliveries</h2><span class="spacer"></span>
          ${lab.deliveries.length ? `<button class="btn secondary small" id="clear-del">Clear</button>` : ""}</div>
        ${lab.deliveries.length ? `<ol class="deliveries">${lab.deliveries.map((d, i) => `
          <li>
            <span class="n">#${lab.deliveries.length - i}</span>
            <div><div class="mono">${esc(d.eventId)} → ${esc(d.status)}</div>
              <div class="muted" style="font-size:13px">${esc(d.text)}</div></div>
            <span class="outcome o-${esc(d.outcome)}">${esc(d.outcome)}</span>
          </li>`).join("")}</ol>`
          : `<p class="empty">Nothing delivered yet.</p>`}
        <p class="explain">Try: deliver <strong>SUCCESS ×3</strong>, then a new event with <strong>FAILED</strong>
          (a late, out-of-order event). Or cancel the booking first, then deliver SUCCESS.</p>
      </section>

      <section class="card full" id="lab-booking"></section>
    </div>`;

  $("[data-go]")?.addEventListener("click", (e) => { e.preventDefault(); go(e.target.dataset.go); });
  const readRef = () => ($("#ref").value === "__custom" ? $("#ref-input").value.trim() : $("#ref").value);

  $("#ref").addEventListener("change", () => {
    const custom = $("#ref").value === "__custom";
    $("#custom-ref").hidden = !custom;
    const p = saved.find((x) => x.provider_reference === $("#ref").value);
    $("#amt").value = p ? p.amount : "";
    lab.ref = readRef();
    drawLabBooking();
  });
  $("#new-evt").addEventListener("click", () => ($("#evt").value = lab.eventId = newEventId()));
  $("#clear-del")?.addEventListener("click", () => { lab.deliveries = []; renderWebhook(); });

  const deliver = async (times) => {
    const body = {
      event_id: $("#evt").value.trim(),
      provider_reference: readRef(),
      status: $("#wh-status").value,
    };
    if ($("#amt").value.trim()) body.amount = $("#amt").value.trim();
    if ($("#reason").value.trim()) body.failure_reason = $("#reason").value.trim();
    lab.ref = body.provider_reference;
    lab.eventId = body.event_id;
    for (let i = 0; i < times; i++) {
      const res = await api("POST", "/payments/webhook", body, { auth: false, quiet: true });
      lab.deliveries.unshift(res.ok
        ? { eventId: body.event_id, status: body.status, outcome: res.data.outcome,
            text: res.data.detail || OUTCOME_TEXT[res.data.outcome] +
              (res.data.booking_status ? ` Booking: ${res.data.booking_status}.` : "") }
        : { eventId: body.event_id, status: body.status, outcome: "error",
            text: `HTTP ${res.status}: ${res.data?.error?.message || "request failed"}` });
    }
    renderWebhook();
  };
  $("#deliver").addEventListener("click", () => deliver(1));
  $("#deliver3").addEventListener("click", () => deliver(3));

  drawLabBooking();
}

async function drawLabBooking() {
  const box = $("#lab-booking");
  const p = savedPayments().find((x) => x.provider_reference === state.lab.ref);
  if (!p) {
    box.innerHTML = `<p class="muted" style="margin:0">Pick a payment you made in this browser to watch its booking change state.</p>`;
    return;
  }
  const res = await api("GET", `/bookings/${p.booking_id}`, undefined, { quiet: true });
  if (!res.ok || !$("#lab-booking")) return;
  const b = res.data;
  box.innerHTML = `
    <div class="row"><h2>Booking #${b.id}</h2><span class="muted">${esc(b.test.name)} · ${esc(b.centre.name)}</span>
      <span class="spacer"></span><span class="badge s-${b.status}">${b.status}</span></div>
    ${stateMachine(b.status)}`;
}

/* ----------------------------------------------------------------- boot */

document.querySelectorAll("#tabs button").forEach((b) =>
  b.addEventListener("click", () => go(b.dataset.view)));

$("#clear-log").addEventListener("click", () => {
  $("#log").innerHTML = `<li class="log-empty">Cleared.</li>`;
});
$("#log").innerHTML = `<li class="log-empty">Requests will appear here.</li>`;

render();
