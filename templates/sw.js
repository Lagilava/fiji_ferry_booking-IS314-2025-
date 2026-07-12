/* Fiji Ferry service worker.
 *
 * Goal: boarding passes must render at remote jetties with no signal.
 *  - Ticket pages + QR images: network-first with a persistent cache fallback,
 *    so every ticket the customer has opened once keeps working offline.
 *  - Static assets: stale-while-revalidate.
 *  - Other navigations: network-first, falling back to the offline page.
 */
const VERSION = 'ferry-v2'; // v2: theme-aware offline page
const OFFLINE_URL = '/offline/';
const PRECACHE = [
  OFFLINE_URL,
  '/static/manifest.webmanifest',
  '/static/android-chrome-192x192.png',
  '/static/android-chrome-512x512.png'
];

// Anything a boarding pass needs offline.
const TICKET_PATTERNS = [
  /^\/bookings\/ticket\/\d+\//,
  /^\/bookings\/view_ticket\//,
  /^\/bookings\/ticket_qr\//,
  /^\/media\/qr_codes\//
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(VERSION).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function isTicketRequest(url) {
  return TICKET_PATTERNS.some((re) => re.test(url.pathname));
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Never cache authenticated/dynamic API or admin traffic.
  if (url.pathname.startsWith('/admin') || url.pathname.includes('/api/')) return;

  if (isTicketRequest(url)) {
    // Network-first; a fresh copy replaces the cached one, but offline the
    // last-seen ticket still renders.
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(VERSION).then((c) => c.put(req, copy));
          }
          return res;
        })
        .catch(() => caches.match(req).then((hit) => hit || caches.match(OFFLINE_URL)))
    );
    return;
  }

  if (url.pathname.startsWith('/static/') || url.pathname.startsWith('/media/')) {
    // Stale-while-revalidate for assets.
    event.respondWith(
      caches.match(req).then((hit) => {
        const refresh = fetch(req)
          .then((res) => {
            if (res && res.ok) {
              const copy = res.clone();
              caches.open(VERSION).then((c) => c.put(req, copy));
            }
            return res;
          })
          .catch(() => hit);
        return hit || refresh;
      })
    );
    return;
  }

  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(() =>
        caches.match(req).then((hit) => hit || caches.match(OFFLINE_URL))
      )
    );
  }
});
