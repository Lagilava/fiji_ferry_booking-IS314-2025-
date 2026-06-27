/* admin_live_refresh.js — live updates for server-rendered admin tool pages.
 *
 * Project rule: every change must reflect live (no manual refresh) on both the
 * admin and client side. The admin dashboard index already streams over the
 * `admin_dashboard` WebSocket group (see bookings/consumers.py + signals.py);
 * the custom "tool" pages (Operations, Departure Manifest, …) historically did
 * a crude full-page reload or nothing at all. This script wires those pages
 * into the SAME live channel and re-renders just their content region in place.
 *
 * Strategy:
 *   1. Open the admin dashboard WebSocket. On any data-changing event
 *      (booking/payment/schedule/ticket/maintenance/alerts), debounce-refresh
 *      the page's content region by fetching the current URL and swapping in
 *      the fresh markup — no full reload, scroll and form focus preserved.
 *   2. If the socket can't connect (or drops), fall back to periodic polling so
 *      the page is still live without WebSockets.
 *
 * Opt in per page:  <element id="content-main" data-live-refresh> … </element>
 * Optional attrs on that element:
 *   data-live-selector="#content-main"  CSS selector of the region to swap (default: the element itself)
 *   data-live-poll="20000"               fallback poll interval in ms (default 20000)
 */
(function () {
  "use strict";

  var host = document.querySelector("[data-live-refresh]");
  if (!host) return;

  var SELECTOR = host.getAttribute("data-live-selector") ||
                 (host.id ? "#" + host.id : null);
  if (!SELECTOR) { host.id = "live-refresh-host"; SELECTOR = "#live-refresh-host"; }

  var POLL_MS = parseInt(host.getAttribute("data-live-poll"), 10) || 20000;

  // Event types (from consumers.py) that mean "underlying data changed".
  var RELEVANT = {
    booking_update: 1, payment_update: 1, schedule_update: 1, ticket_update: 1,
    maintenancelog_update: 1, model_update: 1, weather_alerts: 1,
    weather_alerts_update: 1, critical_alerts: 1, system_notifications: 1,
    cache_cleared: 1
  };

  var ws = null, pollTimer = null, debounceTimer = null, reconnectTimer = null;
  var destroyed = false;

  // ── tiny "live" status pill ──────────────────────────────────────────────
  var pill = document.createElement("div");
  pill.className = "live-pill";
  pill.innerHTML = '<span class="live-dot"></span><span class="live-text">Connecting…</span>';
  pill.style.cssText =
    "position:fixed;bottom:1rem;left:1rem;z-index:11000;display:flex;align-items:center;" +
    "gap:.45rem;padding:.35rem .7rem;border-radius:999px;background:rgba(15,23,42,.9);" +
    "color:#e2e8f0;font:600 .72rem/1 Inter,system-ui,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.25);";
  var styleEl = document.createElement("style");
  styleEl.textContent =
    ".live-pill .live-dot{width:8px;height:8px;border-radius:50%;background:#f59e0b;" +
    "box-shadow:0 0 0 0 rgba(245,158,11,.6);animation:livePulse 1.6s infinite}" +
    ".live-pill.is-live .live-dot{background:#10b981;box-shadow:0 0 0 0 rgba(16,185,129,.6)}" +
    ".live-pill.is-poll .live-dot{background:#3b82f6}" +
    "@keyframes livePulse{0%{box-shadow:0 0 0 0 rgba(16,185,129,.55)}" +
    "70%{box-shadow:0 0 0 7px rgba(16,185,129,0)}100%{box-shadow:0 0 0 0 rgba(16,185,129,0)}}" +
    "@keyframes liveFlash{0%{background:rgba(16,185,129,.18)}100%{background:transparent}}";
  document.head.appendChild(styleEl);
  document.body.appendChild(pill);

  function setStatus(mode, text) {
    pill.classList.toggle("is-live", mode === "live");
    pill.classList.toggle("is-poll", mode === "poll");
    pill.querySelector(".live-text").textContent = text;
  }

  // ── content swap ─────────────────────────────────────────────────────────
  function isEditing(el) {
    var a = document.activeElement;
    return a && el.contains(a) && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName);
  }

  function refresh() {
    if (destroyed || document.hidden) return;
    var el = document.querySelector(SELECTOR);
    if (!el || isEditing(el)) return;   // don't clobber a field being typed in
    fetch(window.location.href, { headers: { "X-Requested-With": "XMLHttpRequest" }, credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.text() : Promise.reject(r.status); })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, "text/html");
        var fresh = doc.querySelector(SELECTOR);
        var current = document.querySelector(SELECTOR);
        if (!fresh || !current || isEditing(current)) return;
        if (fresh.innerHTML !== current.innerHTML) {
          current.innerHTML = fresh.innerHTML;
          current.style.animation = "liveFlash .8s ease";
          setTimeout(function () { current.style.animation = ""; }, 850);
        }
        stampUpdated();
      })
      .catch(function () { /* keep last good content */ });
  }

  function stampUpdated() {
    var t = new Date().toLocaleTimeString();
    var label = pill.classList.contains("is-live") ? "Live" : "Polling";
    setStatus(pill.classList.contains("is-live") ? "live" : "poll", label + " · " + t);
  }

  function scheduleRefresh() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(refresh, 1200);  // coalesce bursts of events
  }

  // ── polling fallback ─────────────────────────────────────────────────────
  function startPolling() {
    if (pollTimer) return;
    setStatus("poll", "Polling");
    pollTimer = setInterval(refresh, POLL_MS);
  }
  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  // ── WebSocket to the existing admin dashboard group ──────────────────────
  function connect() {
    if (destroyed) return;
    var proto = window.location.protocol === "https:" ? "wss" : "ws";
    try {
      ws = new WebSocket(proto + "://" + window.location.host + "/ws/admin/dashboard/");
    } catch (e) { startPolling(); return; }

    ws.onopen = function () {
      stopPolling();
      setStatus("live", "Live");
      // heartbeat so proxies keep the socket open
      ws._hb = setInterval(function () {
        if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "ping" }));
      }, 25000);
    };
    ws.onmessage = function (ev) {
      try {
        var d = JSON.parse(ev.data);
        if (d && RELEVANT[d.type]) scheduleRefresh();
      } catch (e) { /* ignore non-JSON / pong */ }
    };
    ws.onclose = function () {
      if (ws && ws._hb) clearInterval(ws._hb);
      ws = null;
      startPolling();                       // stay live while disconnected
      if (!destroyed) {
        clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(connect, 8000);
      }
    };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
  }

  // Refresh the moment the tab regains focus.
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) refresh();
  });
  window.addEventListener("beforeunload", function () {
    destroyed = true;
    stopPolling();
    if (ws) { try { ws.close(); } catch (e) {} }
  });

  setStatus("poll", "Connecting…");
  connect();
  // Safety net: even with a healthy socket, reconcile occasionally.
  setInterval(function () { if (!ws) refresh(); }, POLL_MS);
})();
