/* global Stripe, AOS, window, document, FormData */

(function () {
  'use strict';

  // ==========
  // Boot logs
  // ==========
  console.log('Book.js loaded successfully');
  console.log('initializeBookingSystem available:', typeof initializeBookingSystem === 'function' ? initializeBookingSystem : 'function');

  // ==========
  // Utilities
  // ==========
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const on = (el, evt, fn, opts) => el && el.addEventListener(evt, fn, opts);

  // Safe CSS escape fallback
  const esc = (s) => {
    if (!s && s !== 0) return '';
    if (window.CSS && typeof CSS.escape === 'function') return CSS.escape(String(s));
    return String(s).replace(/["\\]/g, '\\$&');
  };

  const readMeta = (name) => {
    try {
      const m = document.querySelector(`meta[name="${name}"]`);
      return m ? m.getAttribute('content') : '';
    } catch { return ''; }
  };

  // --- Robust CSRF token getter (cookie → hidden input → meta → window fallback) ---
  function getCsrfToken() {
    try {
      const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
      if (m) return decodeURIComponent(m[1]);
    } catch {}
    const inp = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (inp?.value) return inp.value;
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta?.content) return meta.content;
    return (window.csrfToken || '').trim();
  }

  function money(n, currency = 'FJD') {
    try {
      const v = typeof n === 'string' ? parseFloat(n) : n;
      if (!isFinite(v)) return '0.00';
      return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(v);
    } catch {
      const v = typeof n === 'string' ? parseFloat(n) : n;
      return (isFinite(v) ? `${currency} ${v.toFixed(2)}` : '0.00');
    }
  }

  function parseServerDate(s) {
    if (!s) return null;
    // normalize common "YYYY-MM-DD HH:mm:ss" → "YYYY-MM-DDTHH:mm:ss"
    const isoish = s.replace(' ', 'T');
    let d = new Date(isoish);
    if (!isNaN(d)) return d;

    // Try manual parse "YYYY-MM-DD HH:mm[:ss]"
    const m = s.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$/);
    if (m) {
      const [_, Y, M, D, h, mn, sc] = m;
      d = new Date(
        Number(Y),
        Number(M) - 1,
        Number(D),
        Number(h),
        Number(mn),
        Number(sc || 0)
      );
      if (!isNaN(d)) return d;
    }
    return null;
  }

  function formatDateTime(s) {
    const d = s instanceof Date ? s : parseServerDate(s);
    if (!d) return s || '';
    try {
      return new Intl.DateTimeFormat(undefined, {
        weekday: 'short', month: 'short', day: '2-digit',
        hour: '2-digit', minute: '2-digit'
      }).format(d);
    } catch {
      return d.toLocaleString();
    }
  }

  function formatDateLabel(d) {
    try {
      return new Intl.DateTimeFormat(undefined, {
        weekday: 'short', month: 'short', day: '2-digit'
      }).format(d);
    } catch {
      return d.toDateString();
    }
  }

  function formatTimeLabel(d) {
    try {
      return new Intl.DateTimeFormat(undefined, {
        hour: '2-digit', minute: '2-digit'
      }).format(d);
    } catch {
      return d.toLocaleTimeString();
    }
  }

  function normalizeScheduleList(json) {
    if (Array.isArray(json)) return json;
    if (Array.isArray(json.schedules)) return json.schedules;
    if (Array.isArray(json.bookings)) return json.bookings;
    if (Array.isArray(json.results)) return json.results;
    if (Array.isArray(json.data)) return json.data;
    // allow {items:[...]}
    if (Array.isArray(json.items)) return json.items;
    return [];
  }

  async function apiFetch(url, { method = 'GET', data = null, headers = {} } = {}) {
    const opts = { method, headers: { ...headers } };
    if (data instanceof FormData) {
      opts.body = data;
    } else if (data && typeof data === 'object') {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(data);
    }
    try {
      const res = await fetch(url, opts);
      const ct = res.headers.get('Content-Type') || '';
      if (!res.ok) {
        let errTxt = `${res.status} ${res.statusText}`;
        try {
          if (ct.includes('application/json')) {
            const j = await res.json();
            throw { status: res.status, data: j };
          } else {
            const t = await res.text();
            throw { status: res.status, data: t };
          }
        } catch (e) {
          if (e && e.status) throw e; // propagate parsed
          throw errTxt;
        }
      }
      if (ct.includes('application/json')) return await res.json();
      return await res.text();
    } catch (e) {
      console.error('API error:', e);
      throw e;
    }
  }

  // --- OTP helpers (client-side convenience; server enforces anyway) ---
  async function postForm(url, dataObj) {
    const fd = new FormData();
    Object.entries(dataObj).forEach(([k, v]) => fd.append(k, v));
    const csrf = getCsrfToken();
    console.log('[OTP] POST', url, 'payload=', dataObj, 'csrftoken=', csrf ? '(present)' : '(missing)');
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf },
      body: fd
    });
    let json = {};
    try {
      json = await res.json();
    } catch {
      json = {};
    }
    console.log('[OTP] Response', url, 'status=', res.status, 'json=', json);
    return { ok: res.ok, json };
  }

  function setOtpUIState(msg, good = false) {
    const el = document.getElementById('otp-status');
    if (!el) return;
    el.textContent = msg || '';
    el.className = 'text-sm mt-2 ' + (good ? 'text-green-600' : 'text-red-600');
  }

  // Persist minimal form data in sessionStorage so back/refresh keeps state
  const STORAGE_KEY = 'ffb_booking_form';
  function saveFormData(obj) {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(obj));
      console.log('Form data saved');
    } catch (e) {
      console.warn('saveFormData failed', e);
    }
  }
  function loadFormData() {
    try {
      const json = sessionStorage.getItem(STORAGE_KEY);
      return json ? JSON.parse(json) : {};
    } catch {
      return {};
    }
  }

  // ==========================
  // Globals injected by Django
  // ==========================
  const urls = (window.urls || {
    getPricing: '/bookings/api/pricing/',
    createCheckoutSession: '/bookings/api/create_checkout_session/',
    getActiveSchedules: '/bookings/api/bookings/'
  });
  // Provide OTP endpoints if not injected
  if (!urls.sendOtp) urls.sendOtp = '/bookings/api/send_otp/';
  if (!urls.verifyOtp) urls.verifyOtp = '/bookings/api/verify_otp/';
  // Provide validate_step endpoint if not injected (server-side gate for step transitions)
  if (!urls.validateStep) urls.validateStep = '/bookings/api/validate_step/';
  const bookingConfig = window.bookingConfig || {};
  const validation = window.validationUtils || {};
  console.log('URLs configured:', urls);

  // =========
  // Elements
  // =========
  const form = $('#booking-form');
  const stepInput = $('#current-step');
  const progressBarFill = $('#progress-bar-fill');

  const scheduleSelect = $('#schedule_id');
  const guestEmail = $('#guest_email');

  const adultCountInput = $('#passenger_adults');
  const childCountInput = $('#passenger_children');
  const infantCountInput = $('#passenger_infants');

  const adultFieldsWrap = $('#adult-fields');
  const childFieldsWrap = $('#child-fields');
  const infantFieldsWrap = $('#infant-fields');

  const passengerTemplate = $('#passenger-field-template');

  const addVehicleCheckbox = $('#add_vehicle');
  const vehicleFields = $('#vehicle-fields');
  const vehicleType = $('#vehicle_type');
  const vehicleDimensions = $('#vehicle_dimensions');
  const vehicleLicense = $('#vehicle_license_plate');

  const addCargoCheckbox = $('#add_cargo');
  const cargoFields = $('#cargo-fields');
  const cargoType = $('#cargo_type');
  const cargoWeight = $('#cargo_weight_kg');
  const cargoDims = $('#cargo_dimensions_cm');
  const cargoLicense = $('#cargo_license_plate');

  const summaryBox = $('#booking-summary');
  const privacyConsent = $('#privacy_consent');
  const submitBtn = $('#submit-booking');

  // OTP UI elements (if present in template for guests)
  const sendOtpBtn = document.getElementById('send-otp');
  const verifyOtpBtn = document.getElementById('verify-otp');
  const otpArea = document.getElementById('otp-area');
  const otpCodeInput = document.getElementById('otp_code');

  // *** Inject one-time CSS for subtle animations + theme vars (light/dark)
  (function injectOnce() {
    if (document.getElementById('ffb-anim-css')) return;
    const css = document.createElement('style');
    css.id = 'ffb-anim-css';
    css.textContent = `
      :root {
        --surface: #ffffff;
        --surface-muted: #f8fafc;
        --border: #e5e7eb;
        --text-primary: #0f172a;
        --text-secondary: #475569;
        --primary: #2563eb;
        --gradient-primary: linear-gradient(90deg, #2563eb, #0ea5e9);
      }
      html.dark,:root[data-theme="dark"],.dark {
        --surface: #0b1220;
        --surface-muted: #0f172a;
        --border: #1f2a44;
        --text-primary: #e5e7eb;
        --text-secondary: #a3b0c2;
        --primary: #60a5fa;
        --gradient-primary: linear-gradient(90deg, #2563eb, #22d3ee);
      }

      /* SCHEDULE SELECT shimmer on refresh */
      .ffb-shimmer { position: relative; overflow: hidden; }
      .ffb-shimmer::after {
        content: '';
        position: absolute; inset: 0;
        background: linear-gradient(110deg, transparent 0%, transparent 40%, rgba(255,255,255,.18) 50%, transparent 60%, transparent 100%);
        transform: translateX(-100%);
        animation: ffb-shimmer-move 1s ease-out 1;
        pointer-events: none;
      }
      @keyframes ffb-shimmer-move { to { transform: translateX(100%); } }

      /* Fade-in options container */
      .ffb-fadein { animation: ffb-fade .35s ease-out; }
      @keyframes ffb-fade { from { opacity:.0; transform: translateY(-2px); } to { opacity:1; transform:none; } }

      /* Summary total "blinking lights" (subtle, accessible) */
      .ffb-total-wrap { position: relative; }
      .ffb-total-amount {
        font-weight: 800; font-size: 1.15rem; color: var(--text-primary);
        background: linear-gradient(90deg, var(--text-primary), var(--primary), var(--text-primary));
        -webkit-background-clip: text; background-clip: text; color: transparent;
        animation: ffb-pulse 1.6s ease-in-out infinite alternate;
      }
      .ffb-dot {
        width:.5rem;height:.5rem;border-radius:50%; margin-left:.5rem; flex:0 0 auto;
        background: var(--primary);
        box-shadow: 0 0 .4rem var(--primary);
        animation: ffb-blink 1.2s ease-in-out infinite;
      }
      @keyframes ffb-pulse { from { filter: brightness(1); } to { filter: brightness(1.35); } }
      @keyframes ffb-blink { 0%,100% { opacity:.25 } 50% { opacity:1 } }

      @media (prefers-reduced-motion: reduce) {
        .ffb-shimmer::after, .ffb-fadein, .ffb-total-amount, .ffb-dot { animation: none !important; }
      }
    `;
    document.head.appendChild(css);
  })();

  // NEW: Dedicated, professional summary styles (light/dark aware)
  (function injectSummaryCss() {
    if (document.getElementById('ffb-summary-css')) return;
    const css = document.createElement('style');
    css.id = 'ffb-summary-css';
    css.textContent = `
      .ffb-summary { background: var(--surface-muted); border:1px solid var(--border);
        border-radius: 14px; padding: 1rem; }
      .ffb-schedule-banner {
        background: var(--gradient-primary); color: #fff; border-radius: 10px;
        padding: .85rem 1rem; margin-bottom: 1rem; display:flex; align-items:center;
        justify-content: space-between; gap:.75rem;
      }
      .ffb-schedule-banner .ffb-route { font-weight: 800; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .ffb-schedule-meta { opacity: .95; font-size: .9rem; display:flex; flex-wrap:wrap; gap:.5rem .9rem; margin-top:.2rem; }

      .ffb-summary-grid { display: grid; gap: 1rem; }
      @media (min-width: 768px) {
        .ffb-summary-grid { grid-template-columns: 1.3fr .9fr; }
      }

      .ffb-card {
        background: var(--surface); border:1px solid var(--border);
        border-radius: 10px; padding: .9rem;
      }
      .ffb-card + .ffb-card { margin-top: .8rem; }

      .ffb-section-title { margin: 0 0 .6rem; font-weight: 700; color: var(--text-primary); font-size: 1rem; }

      .ffb-list { list-style: none; padding: 0; margin: 0; }
      .ffb-item { display:flex; justify-content: space-between; align-items: center;
        padding:.45rem 0; border-bottom: 1px dashed var(--border); }
      .ffb-item:last-child { border-bottom: 0; }
      .ffb-name { font-weight: 600; color: var(--text-primary); }
      .ffb-label { color: var(--text-secondary); }
      .ffb-right { opacity: .8; }

      .ffb-chips { display:flex; gap:.4rem; flex-wrap: wrap; margin-left: .5rem; }
      .ffb-chip {
        font-size: .75rem; padding: .1rem .45rem; border:1px solid var(--border);
        border-radius: 9999px; color: var(--text-secondary);
      }

      .ffb-breakdown .ffb-row {
        display:flex; justify-content: space-between; align-items: baseline; padding:.35rem 0;
      }

      .ffb-total { border-top: 1px dashed var(--border); margin-top: .8rem; padding-top: .65rem;
        display:flex; justify-content: space-between; align-items: baseline; }
      .ffb-total .ffb-total-label { font-weight: 800; color: var(--text-primary); }
      .ffb-total .ffb-total-amount { font-weight: 900; font-size: 1.2rem; color: var(--text-primary); background: none; animation: none; }

      .ffb-meta-grid { display:grid; grid-template-columns: 1fr 1fr; gap: .4rem .75rem; }
      .ffb-meta-grid .ffb-row { display:flex; justify-content: space-between; }
      .ffb-badge { font-size:.75rem; padding:.15rem .45rem; border-radius: .5rem; border:1px solid var(--border); color: var(--text-secondary); }

      /* Loader in summary */
      .ffb-loader { text-align:center; }
      .ffb-spin {
        width:40px;height:40px;border-radius:50%;
        border:4px solid var(--border); border-top-color: var(--primary);
        margin:0 auto 12px; animation: ffb-spin .8s linear infinite;
      }
      @keyframes ffb-spin { to { transform: rotate(360deg); } }
      @media (prefers-reduced-motion: reduce) { .ffb-spin { animation: none; } }

      /* Print tidy */
      @media print {
        .ffb-summary { border:0; padding:0; }
        .ffb-schedule-banner { color:#000; background:#fff; border:1px solid #000; }
      }
    `;
    document.head.appendChild(css);
  })();

  // ==================================
  // Preload schedule route name hints
  // ==================================
  const scheduleHints = {};
  (function preloadScheduleHints() {
    if (!scheduleSelect) return;
    const optionNodes = $$('option', scheduleSelect);
    optionNodes.forEach(opt => {
      const id = (opt.value || '').trim();
      if (!id) return;
      const txt = (opt.textContent || '').trim();
      let from = '', to = '';
      const m = txt.match(/^\s*(.+?)\s+to\s+(.+?)\s+-/i);
      if (m) {
        from = (m[1] || '').trim();
        to = (m[2] || '').trim();
      }
      if (!from || !to) {
        const m2 = txt.match(/•\s*(.+?)\s*→\s*(.+?)(?:\s*•|$)/);
        if (m2) {
          from = (m2[1] || '').trim();
          to = (m2[2] || '').trim();
        }
      }
      if (from || to) {
        scheduleHints[id] = { from, to };
      }
    });
    console.log('Preloaded schedule hints:', scheduleHints);
  })();

  // Small helper to read URL params
  function getParam(name) {
    try {
      return new URLSearchParams(window.location.search).get(name);
    } catch {
      return null;
    }
  }

  // ============ STRIPE LAZY INIT ============
  async function ensureStripe(hintKey) {
    try {
      if (window.stripe && typeof window.stripe.redirectToCheckout === 'function') {
        return window.stripe;
      }
      // choose publishable key from several places
      const key =
        hintKey ||
        window.STRIPE_PUBLISHABLE_KEY ||
        window.stripePublishableKey ||
        readMeta('stripe-publishable-key');

      if (!key) {
        console.warn('No Stripe publishable key available yet.');
        return null;
      }
      if (typeof Stripe !== 'function') {
        console.warn('Stripe.js not loaded');
        return null;
      }
      window.stripe = Stripe(key);
      return window.stripe;
    } catch (e) {
      console.error('ensureStripe failed:', e);
      return null;
    }
  }

  // ============ STEP control ============
  function showStep(step) {
    const steps = $$('.form-step');
    steps.forEach(s => {
      const is = String(s.dataset.step) === String(step);
      s.classList.toggle('active', is);
      s.style.display = is ? 'block' : 'none';
    });

    // progress bar
    const maxSteps = 4;
    const pct = Math.max(1, Math.min(maxSteps, Number(step))) / maxSteps * 100;
    if (progressBarFill) progressBarFill.style.width = `${pct}%`;

    // step nav
    $$('.steps .step').forEach(li => {
      const s = Number(li.getAttribute('data-step'));
      li.classList.toggle('active', s <= Number(step));
    });

    console.log(`Step ${step} shown`);
  }

  function currentStep() {
    return Number(stepInput?.value || 1);
  }

  function gotoStep(step) {
    if (stepInput) stepInput.value = String(step);
    showStep(step);
    persistForm();
    if (step === 4) {
      buildSummary();
    }
  }

  // ============ Schedules ============
  function localDateKey(d) {
    if (!(d instanceof Date)) return 'unknown';
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }

  async function fetchActiveSchedules() {
    try {
      console.log('API Request:', urls.getActiveSchedules);
      const json = await apiFetch(urls.getActiveSchedules, { method: 'GET' });
      let schedules = normalizeScheduleList(json);

      const now = new Date();
      schedules = schedules
        .map(s => {
          const route = s.route || {};
          const depTimeStr =
            s.departure_time || s.departure || s.departureDate || s.departureTime;
          const depDt = parseServerDate(depTimeStr);

          const ferryName =
            (s.ferry && (s.ferry.name || s.ferry.title)) ||
            s.ferry_name ||
            s.ferryName ||
            s.vessel_name ||
            (s.vessel && s.vessel.name) ||
            '';

          let fromName =
            route?.departure_port?.name ||
            route?.from?.name ||
            route?.departure ||
            s.departure_port_name ||
            s.departure_port ||
            s.from_port ||
            s.from ||
            '';
          let toName =
            route?.destination_port?.name ||
            route?.to?.name ||
            route?.destination ||
            s.destination_port_name ||
            s.destination_port ||
            s.to_port ||
            s.to ||
            '';

          if ((!fromName || !toName) && (route?.name || s.route_name || s.route)) {
            const rtxt = (route?.name || s.route_name || s.route || '').toString();
            const m = rtxt.match(/^\s*(.+?)\s+to\s+(.+?)\s*$/i);
            if (m) {
              fromName = fromName || (m[1] || '').trim();
              toName = toName || (m[2] || '').trim();
            }
          }

          if ((!fromName || !toName) && scheduleHints) {
            const idGuess = s.id || s.schedule_id || s.pk;
            const hint = scheduleHints[String(idGuess)] || null;
            if (hint) {
              fromName = fromName || hint.from || '';
              toName = toName || hint.to || '';
            }
          }

          const status = (s.status || 'scheduled').toString().toLowerCase();

          return {
            raw: s,
            id: s.id || s.schedule_id || s.pk,
            status,
            available_seats: Number(
              s.available_seats ?? s.seats_available ?? s.remaining ?? 0
            ),
            departure_time: depTimeStr,
            departure_dt: depDt,
            ferry_name: ferryName,
            route: {
              departure_port: { name: fromName || '' },
              destination_port: { name: toName || '' }
            }
          };
        })
        .filter(s => {
          // Only upcoming, scheduled, with seats and a valid datetime
          if (s.status !== 'scheduled') return false;
          if (!(s.available_seats > 0)) return false;
          if (!s.departure_dt) return false;
          return s.departure_dt > now;
        })
        .sort((a, b) => {
          const ad = a.departure_dt ? a.departure_dt.getTime() : 0;
          const bd = b.departure_dt ? b.departure_dt.getTime() : 0;
          return ad - bd;
        });

      console.log('Active schedules populated and grouped:', schedules.length);
      renderScheduleSelect(schedules);
      return schedules;
    } catch (e) {
      console.error('Failed to load schedules', e);
      return [];
    }
  }

  function renderScheduleSelect(schedules) {
    if (!scheduleSelect) return;

    // *** shimmer on refresh
    scheduleSelect.classList.add('ffb-shimmer');

    const current = scheduleSelect.value;
    const desired = getParam('schedule_id'); // preselect if coming from schedule_list
    scheduleSelect.innerHTML = '';

    // Placeholder
    const ph = document.createElement('option');
    ph.value = '';
    ph.textContent = 'Choose a schedule';
    scheduleSelect.appendChild(ph);

    if (!schedules || schedules.length === 0) {
      scheduleSelect.classList.remove('ffb-shimmer');
      return;
    }

    // *** Group by local date (skip items with bad dates)
    const groups = schedules.reduce((acc, s) => {
      const d = s.departure_dt || parseServerDate(s.departure_time);
      if (!d) return acc;
      const key = localDateKey(d);
      if (!acc[key]) acc[key] = [];
      acc[key].push(s);
      return acc;
    }, {});

    const keys = Object.keys(groups).sort(); // chronological by date

    keys.forEach(key => {
      const list = groups[key];
      const anyDate = list[0]?.departure_dt || parseServerDate(list[0]?.departure_time);
      const label = anyDate ? formatDateLabel(anyDate) : 'Other Dates';
      const og = document.createElement('optgroup');
      og.label = label;
      og.className = 'ffb-fadein'; // *** fade in each date group

      list.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.id;

        let rp = s.route?.departure_port?.name || '';
        let rd = s.route?.destination_port?.name || '';
        if ((!rp || !rd) && scheduleHints[String(s.id)]) {
          rp = rp || scheduleHints[String(s.id)]?.from || '';
          rd = rd || scheduleHints[String(s.id)]?.to || '';
        }
        rp = rp || '—';
        rd = rd || '—';

        const dt = s.departure_dt || parseServerDate(s.departure_time);
        const timeTxt = dt ? formatTimeLabel(dt) : (s.departure_time || '');
        const dateTxt = dt ? formatDateLabel(dt) : '';

        const ferry = s.ferry_name ? ` • Ferry: ${s.ferry_name}` : '';
        const seats = ` • ${s.available_seats} ${s.available_seats === 1 ? 'seat' : 'seats'}`;

        opt.textContent = `${timeTxt} • ${rp} → ${rd}${ferry}${seats}`;
        opt.title = `${formatDateTime(dt || s.departure_time)}\nRoute: ${rp} → ${rd}\n${s.ferry_name ? `Ferry: ${s.ferry_name}\n` : ''}Seats available: ${s.available_seats}`;

        opt.dataset.time = timeTxt || '';
        opt.dataset.date = dateTxt || '';
        opt.dataset.from = rp || '';
        opt.dataset.to = rd || '';
        opt.dataset.ferry = s.ferry_name || '';
        opt.dataset.seats = String(s.available_seats);

        og.appendChild(opt);
      });

      scheduleSelect.appendChild(og);
    });

    // try to keep selection (URL param beats previous selection)
    if (desired && $(`option[value="${esc(desired)}"]`, scheduleSelect)) {
      scheduleSelect.value = desired;
    } else if (current && $(`option[value="${esc(current)}"]`, scheduleSelect)) {
      scheduleSelect.value = current;
    }

    // Persist immediately if we locked a selection
    if (scheduleSelect.value) persistForm();

    // *** remove shimmer after a tick
    setTimeout(() => scheduleSelect.classList.remove('ffb-shimmer'), 650);
  }

  // ==================
  // Passenger handling
  // ==================
  function getCounts() {
    const adults = Number(adultCountInput?.value || 0);
    const children = Number(childCountInput?.value || 0);
    const infants = Number(infantCountInput?.value || 0);
    return { adults, children, infants };
  }

  function updatePassengerFields() {
    console.log('Updating passenger fields...');
    const { adults, children, infants } = getCounts();
    console.log('Passenger counts:', { adults, children, infants });

    renderPassengerCards('adult', adults, adultFieldsWrap);
    renderPassengerCards('child', children, childFieldsWrap);
    renderPassengerCards('infant', infants, infantFieldsWrap);

    populateLinkedAdults();
    persistForm();
  }

  function renderPassengerCards(type, count, container) {
    if (!container || !passengerTemplate) return;

    const existing = {};
    $$('input, select', container).forEach(inp => {
      existing[inp.name] = (inp.type === 'file') ? null : inp.value;
    });

    container.innerHTML = '';

    for (let i = 0; i < count; i++) {
      const node = passengerTemplate.content.cloneNode(true);
      const card = $('.passenger-card', node);
      const header = $('.passenger-header', node);
      const title = $('.passenger-title', node);

      if (title) title.textContent = `${type.charAt(0).toUpperCase() + type.slice(1)} Passenger #${i + 1}`;

      $$('input, select', node).forEach(inp => {
        const origName = inp.getAttribute('name');
        const name = origName
          .replace(/{type}/g, type)
          .replace(/{index}/g, String(i));
        inp.setAttribute('name', name);

        if (!inp.id) inp.id = name;

        const forNonInfant = inp.closest('[data-for="non-infant"]');
        const forInfant = inp.closest('[data-for="infant"]');
        const forChildInfant = inp.closest('[data-for="child-infant"]');
        if (type === 'infant') {
          if (forNonInfant) forNonInfant.style.display = 'none';
          if (forInfant) forInfant.style.display = '';
          if (forChildInfant) forChildInfant.style.display = '';
        } else {
          if (forNonInfant) forNonInfant.style.display = '';
          if (forInfant) forInfant.style.display = 'none';
          if (forChildInfant) forChildInfant.style.display = (type === 'child') ? '' : 'none';
        }

        if (existing[name] != null && inp.type !== 'file') {
          inp.value = existing[name];
        }

        if (inp.type === 'file') {
          on(inp, 'change', async (e) => {
            if (!validation.validateFile) return;
            const file = e.currentTarget.files?.[0];
            await validation.validateFile(file, e.currentTarget);
          });
        }
      });

      on(header, 'click', () => {
        const content = $('.passenger-content', card);
        const expanded = header.getAttribute('aria-expanded') === 'true';
        header.setAttribute('aria-expanded', !expanded);
        content.style.display = expanded ? 'none' : '';
      });

      container.appendChild(node);
    }

    console.log(`${type} fields generated and restored: ${count}`);
  }

  function populateLinkedAdults() {
    const adults = [];
    const { adults: count } = getCounts();
    for (let i = 0; i < count; i++) {
      const fn = $(`[name="adult_first_name_${esc(i)}"]`)?.value?.trim() || `Adult ${i + 1}`;
      const ln = $(`[name="adult_last_name_${esc(i)}"]`)?.value?.trim() || '';
      adults.push({ idx: i, label: `${fn} ${ln}`.trim() });
    }

    ['child', 'infant'].forEach(type => {
      const { children, infants } = getCounts();
      const max = type === 'child' ? children : infants;
      for (let i = 0; i < max; i++) {
        const sel = $(`[name="${esc(type)}_linked_adult_${esc(i)}"]`);
        if (!sel) continue;
        const cur = sel.value;
        sel.innerHTML = '<option value="">Select adult passenger</option>';
        adults.forEach(a => {
          const opt = document.createElement('option');
          opt.value = String(a.idx);
          opt.textContent = a.label;
          sel.appendChild(opt);
        });
        if (cur && $(`option[value="${esc(cur)}"]`, sel)) sel.value = cur;
      }
    });

    console.log('Linked adults populated');
  }

  // ==========
  // Add-ons UI
  // ==========
  function readAddOns() {
    const out = [];
    (bookingConfig.addOns || []).forEach(a => {
      const inp = $(`[name="${esc(a.id)}_quantity"]`);
      if (!inp) return;
      const qty = Number(inp.value || 0);
      if (qty > 0) {
        out.push({ type: a.id, quantity: qty });
      }
    });
    return out;
  }

  // ==============================
  // Vehicle/Cargo toggle + mapping
  // ==============================
  function updateVehicleVisibility() {
    if (vehicleFields) vehicleFields.classList.toggle('hidden', !addVehicleCheckbox?.checked);
  }
  function updateCargoVisibility() {
    if (cargoFields) cargoFields.classList.toggle('hidden', !addCargoCheckbox?.checked);
  }

  function mapVehicleTypeForBackend(val) {
    if (!val) return '';
    switch (val) {
      case 'van': return 'car';
      case 'truck': return 'car';
      default: return val;
    }
  }
  function mapCargoTypeForBackend(val) {
    if (!val) return '';
    switch (val) {
      case 'luggage': return 'general';
      case 'equipment': return 'perishable';
      case 'freight': return 'vehicle';
      default: return val;
    }
  }

  // ===================
  // Validation + Steps
  // ===================
  function collectClientForm() {
    const fd = new FormData(form);

    const { adults, children, infants } = getCounts();
    fd.set('adults', String(adults));
    fd.set('children', String(children));
    fd.set('infants', String(infants));

    if (scheduleSelect) {
      fd.set('schedule_id', scheduleSelect.value || '');
    }

    if (guestEmail) {
      fd.set('guest_email', guestEmail.value?.trim() || '');
    }

    if (addVehicleCheckbox) {
      const onV = addVehicleCheckbox.checked;
      fd.set('add_vehicle', onV ? 'on' : '');
      if (onV) {
        fd.set('vehicle_type', mapVehicleTypeForBackend(vehicleType?.value || ''));
        fd.set('vehicle_dimensions', (vehicleDimensions?.value || '').trim());
        fd.set('vehicle_license_plate', (vehicleLicense?.value || '').trim());
      } else {
        fd.delete('vehicle_type');
        fd.delete('vehicle_dimensions');
        fd.delete('vehicle_license_plate');
      }
    }
    if (addCargoCheckbox) {
      const onC = addCargoCheckbox.checked;
      fd.set('add_cargo', onC ? 'on' : '');
      if (onC) {
        fd.set('cargo_type', mapCargoTypeForBackend(cargoType?.value || ''));
        fd.set('cargo_weight_kg', (cargoWeight?.value || '').trim());
        fd.set('cargo_dimensions_cm', (cargoDims?.value || '').trim());
        fd.set('cargo_license_plate', (cargoLicense?.value || '').trim());
      } else {
        fd.delete('cargo_type');
        fd.delete('cargo_weight_kg');
        fd.delete('cargo_dimensions_cm');
        fd.delete('cargo_license_plate');
      }
    }

    (bookingConfig.addOns || []).forEach(a => {
      const inp = $(`[name="${esc(a.id)}_quantity"]`);
      const qty = inp ? Number(inp.value || 0) : 0;
      fd.set(`${a.id}_quantity`, String(qty));
    });

    const { adults: A, children: C, infants: I } = getCounts();

    // Adults
    for (let i = 0; i < A; i++) {
      const f = $(`[name="adult_id_document_${esc(i)}"]`) || $(`[name="adult_id_document${esc(i)}"]`);
      if (f && f.files && f.files[0]) {
        fd.set(`adult_id_document_${i}`, f.files[0]);
      } else {
        fd.delete(`adult_id_document_${i}`);
      }
      const age = $(`[name="adult_age_${esc(i)}"]`)?.value || '';
      if (age) fd.set(`adult_age_${i}`, age);
      const fn = $(`[name="adult_first_name_${esc(i)}"]`)?.value?.trim() || '';
      const ln = $(`[name="adult_last_name_${esc(i)}"]`)?.value?.trim() || '';
      fd.set(`adult_first_name_${i}`, fn);
      fd.set(`adult_last_name_${i}`, ln);
    }
    // Children
    for (let i = 0; i < C; i++) {
      const f = $(`[name="child_id_document_${esc(i)}"]`) || $(`[name="child_document_${esc(i)}"]`);
      if (f && f.files && f.files[0]) {
        fd.set(`child_id_document_${i}`, f.files[0]);
      } else {
        fd.delete(`child_id_document_${i}`);
      }
      const age = $(`[name="child_age_${esc(i)}"]`)?.value || '';
      if (age) fd.set(`child_age_${i}`, age);
      const fn = $(`[name="child_first_name_${esc(i)}"]`)?.value?.trim() || '';
      const ln = $(`[name="child_last_name_${esc(i)}"]`)?.value?.trim() || '';
      fd.set(`child_first_name_${i}`, fn);
      fd.set(`child_last_name_${i}`, ln);
      const la = $(`[name="child_linked_adult_${esc(i)}"]`)?.value || '';
      if (la) fd.set(`child_linked_adult_${i}`, la);
    }
    // Infants
    for (let i = 0; i < I; i++) {
      const dob = $(`[name="infant_dob_${esc(i)}"]`)?.value || '';
      if (dob) fd.set(`infant_dob_${i}`, dob);

      const f = $(`[name="infant_id_document_${esc(i)}"]`) || $(`[name="infant_document_${esc(i)}"]`);
      if (f && f.files && f.files[0]) {
        fd.set(`infant_id_document_${i}`, f.files[0]); // validator will reject infants with files
      } else {
        fd.delete(`infant_id_document_${i}`);
      }

      const fn = $(`[name="infant_first_name_${esc(i)}"]`)?.value?.trim() || '';
      const ln = $(`[name="infant_last_name_${esc(i)}"]`)?.value?.trim() || '';
      fd.set(`infant_first_name_${i}`, fn);
      fd.set(`infant_last_name_${i}`, ln);
      const la = $(`[name="infant_linked_adult_${esc(i)}"]`)?.value || '';
      if (la) fd.set(`infant_linked_adult_${i}`, la);
    }

    if (privacyConsent) {
      fd.set('privacy_consent', privacyConsent.checked ? 'on' : '');
    }

    fd.set('step', String(currentStep()));

    return fd;
  }

  // Debounced persist
  let _persistTO;
  function persistForm() {
    clearTimeout(_persistTO);
    _persistTO = setTimeout(() => {
      const obj = {};
      const fd = collectClientForm();
      fd.forEach((v, k) => {
        if (v instanceof File) return;
        obj[k] = v;
      });
      saveFormData(obj);
    }, 200);
  }

  async function validateCurrentStepClient() {
    if (!validation || !validation.validateStep) return { valid: true, errors: [] };
    const fd = collectClientForm();
    const formDataObj = {};
    fd.forEach((v, k) => formDataObj[k] = v);

    const step = currentStep();
    const out = validation.validateStep(step, {
      get: (name) => (formDataObj[name] ?? ''), // mimic FormData.get
    });

    if (!out.valid) {
      validation.displayBackendErrors(out.errors, form);
    }
    return out;
  }

  // --- NEW: Server-side step validation (leverages Django `validate_step`) ---
  async function validateStepServer(step) {
    if (!urls.validateStep) return { valid: true, errors: [] };
    try {
      const fd = collectClientForm();
      fd.set('step', String(step));
      const csrf = getCsrfToken();
      const res = await fetch(urls.validateStep, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrf },
        body: fd
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok || json.valid === false) {
        const errs = json.errors || [{ field: 'general', message: json.detail || 'Validation failed' }];
        if (validation && validation.displayBackendErrors) {
          validation.displayBackendErrors(errs, form);
        }
        return { valid: false, errors: errs };
      }
      return { valid: true, errors: [] };
    } catch (e) {
      console.error('Server step validation failed:', e);
      const errs = [{ field: 'general', message: 'Network error while validating this step' }];
      if (validation && validation.displayBackendErrors) {
        validation.displayBackendErrors(errs, form);
      }
      return { valid: false, errors: errs };
    }
  }

  // ==============
  // Pricing/Summary (Presentation-focused refresh)
  // ==============
  let pricingController;

  async function buildSummary() {
    if (!summaryBox) return;

    summaryBox.innerHTML = `
      <div class="ffb-loader ffb-card">
        <div class="ffb-spin" aria-hidden="true"></div>
        <p class="ffb-label">Loading your booking summary…</p>
      </div>
    `;

    try {
      const fd = collectClientForm();

      if (pricingController) pricingController.abort();
      pricingController = new AbortController();

      const csrf = getCsrfToken();
      console.log('[Summary] POST', urls.getPricing, 'csrftoken=', csrf ? '(present)' : '(missing)');
      const res = await fetch(urls.getPricing, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrf },
        body: fd,
        signal: pricingController.signal
      });
      const json = await res.json();
      if (!res.ok) throw json;

      const breakdown = json.breakdown || json.pricing || {};
      const total = breakdown.total || json.total_price || '0.00';

      const scheduleOpt = scheduleSelect?.selectedOptions?.[0];
      const schedule = scheduleOpt ? {
        text: scheduleOpt.textContent,
        date: scheduleOpt.dataset.date || '',
        time: scheduleOpt.dataset.time || '',
        from: scheduleOpt.dataset.from || '',
        to:   scheduleOpt.dataset.to   || '',
        ferry: scheduleOpt.dataset.ferry || '',
        seats: scheduleOpt.dataset.seats || ''
      } : null;

      const { adults, children, infants } = getCounts();

      const passengerHTML = (type, count, prefix) => {
        if (count === 0) return '';
        let html = `
          <div class="ffb-card">
            <div class="ffb-section-title">${type.charAt(0).toUpperCase()+type.slice(1)}s</div>
            <ul class="ffb-list">`;
        for (let i = 0; i < count; i++) {
          const first = $(`[name="${esc(prefix)}_first_name_${esc(i)}"]`)?.value?.trim() || '';
          const last  = $(`[name="${esc(prefix)}_last_name_${esc(i)}"]`)?.value?.trim() || '';
          const age   = $(`[name="${esc(prefix)}_age_${esc(i)}"]`)?.value || '';
          const linked= $(`[name="${esc(prefix)}_linked_adult_${esc(i)}"]`)?.value;
          const chips = [];
          if (age) chips.push(`<span class="ffb-chip">${age} yrs</span>`);
          if (linked !== undefined && linked !== '') chips.push(`<span class="ffb-chip">with Adult ${Number(linked)+1}</span>`);

          html += `
            <li class="ffb-item">
              <div class="ffb-left">
                <span class="ffb-name">${first} ${last}</span>
                ${chips.length ? `<span class="ffb-chips">${chips.join('')}</span>` : ''}
              </div>
              <div class="ffb-right">#${i+1}</div>
            </li>`;
        }
        html += `</ul></div>`;
        return html;
      };

      const vehicleHTML = addVehicleCheckbox?.checked ? `
        <div class="ffb-card">
          <div class="ffb-section-title">Vehicle</div>
          <div class="ffb-meta-grid">
            <div class="ffb-row"><span class="ffb-label">Type</span><span>${vehicleType?.options[vehicleType.selectedIndex]?.text || '—'}</span></div>
            <div class="ffb-row"><span class="ffb-label">License</span><span>${vehicleLicense?.value?.trim() || '—'}</span></div>
            <div class="ffb-row"><span class="ffb-label">Dimensions</span><span>${vehicleDimensions?.value?.trim() || '—'}</span></div>
          </div>
        </div>` : '';

      const cargoHTML = addCargoCheckbox?.checked ? `
        <div class="ffb-card">
          <div class="ffb-section-title">Cargo</div>
          <div class="ffb-meta-grid">
            <div class="ffb-row"><span class="ffb-label">Type</span><span>${cargoType?.options[cargoType.selectedIndex]?.text || '—'}</span></div>
            <div class="ffb-row"><span class="ffb-label">Weight</span><span>${cargoWeight?.value?.trim() || '—'} kg</span></div>
            <div class="ffb-row"><span class="ffb-label">Dimensions</span><span>${cargoDims?.value?.trim() || '—'}</span></div>
            <div class="ffb-row"><span class="ffb-label">License</span><span>${cargoLicense?.value?.trim() || '—'}</span></div>
          </div>
        </div>` : '';

      let addonsRows = '';
      const addons = breakdown.addons || {};
      if (Array.isArray(addons) && addons.length) {
        addonsRows = addons.map(a => `
          <div class="ffb-row"><span class="ffb-label">${(a.type?.replace(/_/g,' ')||a.label||'Add-on')
            .replace(/\b\w/g,c=>c.toUpperCase())}${a.quantity ? ` × ${a.quantity}` : ''}</span>
            <span>${money(a.amount)}</span></div>`).join('');
      } else if (typeof addons === 'object') {
        addonsRows = Object.entries(addons).map(([k, it]) => `
          <div class="ffb-row"><span class="ffb-label">${it.label || k}${it.quantity ? ` × ${it.quantity}` : ''}</span>
            <span>${money(it.amount)}</span></div>`).join('');
      }

      // Compose final summary
      summaryBox.innerHTML = `
        <div class="ffb-summary">
          ${schedule ? `
            <div class="ffb-schedule-banner">
              <div style="min-width:0">
                <div class="ffb-route">${schedule.from} → ${schedule.to}</div>
                <div class="ffb-schedule-meta">
                  ${schedule.date ? `<span class="ffb-badge">${schedule.date}</span>` : ''}
                  ${schedule.time ? `<span class="ffb-badge">${schedule.time}</span>` : ''}
                  ${schedule.ferry ? `<span class="ffb-badge">Ferry: ${schedule.ferry}</span>` : ''}
                  ${schedule.seats ? `<span class="ffb-badge">${schedule.seats} seats left</span>` : ''}
                </div>
              </div>
              <div aria-hidden="true" style="opacity:.9;flex:0 0 auto">⟶</div>
            </div>` : ''}

          <div class="ffb-summary-grid">
            <div>
              <div class="ffb-card">
                <div class="ffb-section-title">Passengers (${adults + children + infants})</div>
                ${passengerHTML('adult', adults, 'adult')}
                ${passengerHTML('child', children, 'child')}
                ${passengerHTML('infant', infants, 'infant')}
              </div>

              ${vehicleHTML}
              ${cargoHTML}
            </div>

            <aside>
              <div class="ffb-card ffb-breakdown">
                <div class="ffb-section-title">Fare Breakdown</div>
                <div class="ffb-row"><span class="ffb-label">Adults (${adults})</span><span>${money(breakdown.adults || 0)}</span></div>
                <div class="ffb-row"><span class="ffb-label">Children (${children})</span><span>${money(breakdown.children || 0)}</span></div>
                <div class="ffb-row"><span class="ffb-label">Infants (${infants})</span><span>${money(breakdown.infants || 0)}</span></div>
                ${breakdown.vehicle ? `<div class="ffb-row"><span class="ffb-label">Vehicle</span><span>${money(breakdown.vehicle)}</span></div>` : ''}
                ${breakdown.cargo   ? `<div class="ffb-row"><span class="ffb-label">Cargo</span><span>${money(breakdown.cargo)}</span></div>` : ''}
                ${addonsRows ? `<div class="ffb-row" style="margin-top:.25rem;border-top:1px dashed var(--border)"></div>${addonsRows}` : ''}
                <div class="ffb-total">
                  <span class="ffb-total-label">Total</span>
                  <span class="ffb-total-amount" aria-live="polite">${money(total)}</span>
                </div>
              </div>
            </aside>
          </div>
        </div>`;
    } catch (e) {
      if (e?.name === 'AbortError') {
        console.log('Pricing request aborted; a newer request is in-flight.');
        return;
      }
      console.error('Summary error:', e);
      summaryBox.innerHTML = `
        <div class="ffb-card ffb-loader">
          <div style="font-size:2rem;margin-bottom:.5rem">⚠️</div>
          <p class="ffb-label">Unable to load the summary. Please review your selections and try again.</p>
        </div>`;
    }
  }

  // =======
  // Stripe
  // =======
  // LOG-3: stable idempotency token so rapid double-clicks / retries of the same
  // checkout dedupe server-side instead of creating duplicate bookings/charges.
  let _checkoutIdemKey = null;
  function getCheckoutIdemKey() {
    if (!_checkoutIdemKey) {
      _checkoutIdemKey = (window.crypto && window.crypto.randomUUID)
        ? window.crypto.randomUUID()
        : ('idem-' + Date.now() + '-' + Math.random().toString(36).slice(2));
    }
    return _checkoutIdemKey;
  }

  async function createCheckout() {
    try {
      // Validate current step first
      const stepValid = await validateCurrentStepClient();
      if (!stepValid.valid) return;

      // Build form data and create session FIRST
      const fd = collectClientForm();
      fd.append('idempotency_key', getCheckoutIdemKey());
      const csrf = getCsrfToken();
      console.log('[Checkout] POST', urls.createCheckoutSession, 'csrftoken=', csrf ? '(present)' : '(missing)');
      const res = await fetch(urls.createCheckoutSession, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrf },
        body: fd
      });

      let json = {};
      try { json = await res.json(); } catch (_) {}

      if (!res.ok) {
        const errs = json.errors || [{ field: 'general', message: (json.detail || 'Checkout failed') }];
        if (validation && validation.displayBackendErrors) {
          validation.displayBackendErrors(errs, form);
        } else {
          alert(errs.map(e => e.message || e).join('\n'));
        }
        return;
      }

      // Some backends return a direct URL for hosted checkout
      if (json && json.url) {
        window.location.assign(json.url);
        return;
      }

      const sessionId = json.sessionId || json.id;
      const pk = json.publishable_key || json.publishableKey || readMeta('stripe-publishable-key') || window.STRIPE_PUBLISHABLE_KEY || window.stripePublishableKey;

      let stripe = await ensureStripe(pk);
      if (!stripe) {
        console.error('Stripe not initialized even after ensureStripe');
        const msg = 'Unable to initialize Stripe on this page. Please refresh and try again.';
        if (validation && validation.displayBackendErrors) {
          validation.displayBackendErrors([{ field: 'general', message: msg }], form);
        } else {
          alert(msg);
        }
        return;
      }

      if (!sessionId) {
        const msg = 'Checkout session was created without an ID.';
        if (validation && validation.displayBackendErrors) {
          validation.displayBackendErrors([{ field: 'general', message: msg }], form);
        } else {
          alert(msg);
        }
        return;
      }

      // Booking + session committed; a later checkout starts a fresh idempotency token.
      _checkoutIdemKey = null;
      await stripe.redirectToCheckout({ sessionId });
    } catch (e) {
      console.error('Checkout error:', e);
      const msg = 'Unable to start checkout. Please try again.';
      if (validation && validation.displayBackendErrors) {
        validation.displayBackendErrors([{ field: 'general', message: msg }], form);
      } else {
        alert(msg);
      }
    }
  }

  // ========================
  // Navigation/event wiring
  // ========================
  function wireStepButtons() {
    $$('.next-step').forEach(btn => {
      on(btn, 'click', async () => {
        const target = Number(btn.getAttribute('data-next') || (currentStep() + 1));

        // client validation guard (single source of truth in validation.js)
        const client = await validateCurrentStepClient();
        if (!client.valid) return;

        // server validation guard (enforces OTP/session on Step 1, etc.)
        const server = await validateStepServer(currentStep());
        if (!server.valid) return;

        gotoStep(target);
      });
    });

    $$('.prev-step').forEach(btn => {
      on(btn, 'click', () => {
        const prev = Number(btn.getAttribute('data-prev') || (currentStep() - 1));
        gotoStep(prev);
      });
    });
  }

  function wireForm() {
    if (!form) return;

    // Counters → redraw passenger sections
    [adultCountInput, childCountInput, infantCountInput].forEach(inp => {
      if (!inp) return;
      ['change', 'input'].forEach(ev => {
        on(inp, ev, () => {
          const v = Number(inp.value || 0);
          const min = Number(inp.getAttribute('min') || 0);
          const max = Number(inp.getAttribute('max') || 999);
          if (v < min) inp.value = String(min);
          if (v > max) inp.value = String(max);
          updatePassengerFields();
        });
      });
    });

    // Vehicle/Cargo toggles
    if (addVehicleCheckbox) {
      on(addVehicleCheckbox, 'change', () => {
        updateVehicleVisibility();
        persistForm();
      });
    }
    if (addCargoCheckbox) {
      on(addCargoCheckbox, 'change', () => {
        updateCargoVisibility();
        persistForm();
      });
    }

    // File inputs – validate on change (delegated)
    on(form, 'change', async (e) => {
      const t = e.target;
      if (t && t.type === 'file' && validation && validation.validateFile) {
        const file = t.files?.[0];
        await validation.validateFile(file, t);
      }
    });

    // Any input → persist
    on(form, 'input', () => persistForm());
    on(form, 'change', () => persistForm());

    // Final submit → Stripe
    if (submitBtn) {
      on(submitBtn, 'click', (e) => {
        e.preventDefault();
        createCheckout();
      });
    }

    // --- OTP UI wiring (optional client convenience; server is source of truth) ---
    if (sendOtpBtn) {
      console.log('[OTP] Wiring sendOtpBtn click handler');
      on(sendOtpBtn, 'click', async () => {
        console.log('[OTP] Send Code clicked');
        const email = (guestEmail?.value || '').trim();
        if (!email) {
          setOtpUIState('Enter your email first.');
          console.warn('[OTP] No email entered');
          return;
        }
        setOtpUIState('Sending code…', true);
        try {
          const { ok, json } = await postForm(urls.sendOtp, { email });
          if (ok && json?.success) {
            otpArea?.classList.remove('hidden');
            setOtpUIState('Code sent! Check your inbox.', true);
          } else {
            setOtpUIState(json?.errors?.[0]?.message || 'Failed to send code.');
          }
        } catch (err) {
          console.error('[OTP] Send error', err);
          setOtpUIState('Failed to send code.');
        }
      });
    } else {
      console.warn('[OTP] sendOtpBtn not found in DOM');
    }

    if (verifyOtpBtn) {
      console.log('[OTP] Wiring verifyOtpBtn click handler');
      on(verifyOtpBtn, 'click', async () => {
        console.log('[OTP] Verify clicked');
        const email = (guestEmail?.value || '').trim();
        const code = (otpCodeInput?.value || '').trim();
        if (!email || !code) {
          setOtpUIState('Enter the code sent to your email.');
          console.warn('[OTP] Missing email or code');
          return;
        }
        setOtpUIState('Verifying…', true);
        try {
          const { ok, json } = await postForm(urls.verifyOtp, { email, code });
          if (ok && json?.success) {
            setOtpUIState('Email verified ✔', true);
            if (guestEmail) {
              guestEmail.readOnly = true;
              guestEmail.classList.add('opacity-70', 'cursor-not-allowed');
            }
            // Persist verification flags (used by client validation)
            sessionStorage.setItem('ffb_guest_verified', '1');
            sessionStorage.setItem('ffb_guest_verified_email', email.toLowerCase());
          } else {
            setOtpUIState(json?.errors?.[0]?.message || 'Verification failed.');
          }
        } catch (err) {
          console.error('[OTP] Verify error', err);
          setOtpUIState('Verification failed.');
        }
      });
    } else {
      console.warn('[OTP] verifyOtpBtn not found in DOM');
    }

    // NEW: If user edits email, clear verification flags & reset UI so they must re-verify
    if (guestEmail) {
      on(guestEmail, 'input', () => {
        try {
          sessionStorage.removeItem('ffb_guest_verified');
          sessionStorage.removeItem('ffb_guest_verified_email');
        } catch (_) {}
        guestEmail.readOnly = false;
        guestEmail.classList.remove('opacity-70', 'cursor-not-allowed');
        otpArea?.classList.add('hidden');
        setOtpUIState('');
      });
    }
  }

  function restoreFromStorage() {
    const saved = loadFormData();
    if (!saved || typeof saved !== 'object') return;

    Object.keys(saved).forEach(k => {
      const el = $(`[name="${esc(k)}"]`, form);
      if (!el) return;
      if (el.type === 'checkbox') {
        el.checked = (saved[k] === 'on' || saved[k] === true || saved[k] === 'true');
      } else if (el.type !== 'file') {
        el.value = saved[k];
      }
    });

    if (saved.step && stepInput) {
      stepInput.value = String(saved.step);
    }
  }

  // ===============
  // Public init API
  // ===============
  let _initialized = false;
  window.initializeBookingSystem = async function initializeBookingSystem() {
    if (_initialized) return;
    _initialized = true;

    console.log('initializeBookingSystem called');

    const checks = {
      urls: !!urls,
      validationLoaded: !!validation,
      form: !!form
    };
    if (!checks.form) {
      console.error('booking form not found');
      return;
    }
    console.log('Core elements found');

    restoreFromStorage();

    wireStepButtons();
    wireForm();

    await fetchActiveSchedules();

    const start = Number(stepInput?.value || 1);
    showStep(start || 1);

    updatePassengerFields();

    updateVehicleVisibility();
    updateCargoVisibility();

    console.log('Booking system fully initialized');
  };

  // ============
  // Safe startup
  // ============
  (function safeInit() {
    try {
      console.log('Initializing booking system...');
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => window.initializeBookingSystem());
      } else {
        window.initializeBookingSystem();
      }
    } catch (e) {
      console.error('Init error:', e);
    }
  })();

})();
