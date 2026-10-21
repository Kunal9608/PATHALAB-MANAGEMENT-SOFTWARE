/**
 * AKRITI — Service Worker
 * Strategy:
 *  - Static assets (CSS, JS, fonts): Cache-first with network fallback
 *  - API calls: Network-first with no cache (auth-sensitive)
 *  - /health: Network-only
 *  - HTML pages: Network-first, fallback to cache, then offline page
 */

const CACHE_VERSION = 'akriti-v3';
const STATIC_CACHE  = `${CACHE_VERSION}-static`;
const PAGES_CACHE   = `${CACHE_VERSION}-pages`;

const STATIC_ASSETS = [
  '/assets/css/tokens.css',
  '/assets/css/components.css',
  '/assets/css/skeleton.css',
  '/assets/css/layout.css',
  '/assets/js/api-client.js',
  '/assets/js/toast.js',
  '/assets/js/modal.js',
  '/assets/js/theme.js',
  '/assets/js/table.js',
  '/assets/js/offline-queue.js',
  '/assets/js/face-capture.js',
  '/assets/js/patient-form.js',
  '/assets/js/shell.js',
];

const HTML_PAGES = [
  '/index.html',
  '/404.html',
  '/offline.html',
  '/admin/dashboard.html',
  '/admin/patients.html',
  '/admin/failed-patients.html',
  '/admin/staff.html',
  '/admin/tests.html',
  '/admin/expenses.html',
  '/admin/revenue.html',
  '/admin/attendance-report.html',
  '/admin/audit-log.html',
  '/admin/settings.html',
  '/admin/add-patient.html',
  '/staff/add-patient.html',
  '/staff/patients.html',
  '/staff/failed-patients.html',
  '/staff/settings.html',
  '/attendance-kiosk.html',
];

// ── Install: pre-cache static assets & html pages ──────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    Promise.all([
      caches.open(STATIC_CACHE).then(cache => cache.addAll(STATIC_ASSETS)),
      caches.open(PAGES_CACHE).then(cache => cache.addAll(HTML_PAGES))
    ]).then(() => self.skipWaiting())
  );
});

// ── Activate: clear old caches ─────────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== STATIC_CACHE && k !== PAGES_CACHE).map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ── Fetch ─────────────────────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET and cross-origin
  if (request.method !== 'GET' || url.origin !== location.origin) return;

  // API calls — network-only (auth cookies, can't cache)
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(request));
    return;
  }

  // Health check — network-only
  if (url.pathname === '/health') {
    event.respondWith(fetch(request));
    return;
  }

  // Static assets (CSS, JS) — cache-first
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(
      caches.match(request).then(cached => {
        if (cached) return cached;
        return fetch(request).then(res => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(STATIC_CACHE).then(c => c.put(request, clone));
          }
          return res;
        });
      })
    );
    return;
  }

  // HTML pages — network-first, fall back to cache
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).then(res => {
        if (res.ok) {
          const clone = res.clone();
          caches.open(PAGES_CACHE).then(c => c.put(request, clone));
        }
        return res;
      }).catch(async () => {
        // 1. Check if the exact requested page is available in local cache
        const cached = await caches.match(request, { ignoreSearch: true });
        if (cached) return cached;
        // 2. Offline fallback: serve dedicated branded offline page (never 404!)
        const offlinePage = await caches.match('/offline.html');
        if (offlinePage) return offlinePage;
        // 3. Fallback to cached index if offline page not yet primed
        const fallback = await caches.match('/index.html');
        if (fallback) return fallback;
        return new Response('PathLab OS is currently offline.', { status: 503, headers: { 'Content-Type': 'text/plain' } });
      })
    );
    return;
  }

  // Other assets (images, fonts not explicitly static)
  event.respondWith(
    fetch(request).then(res => res).catch(() => {
      return caches.match(request).then(cached => {
        if (cached) return cached;
        return new Response('Offline', { status: 503 });
      });
    })
  );
});

// ── Background sync (future) ───────────────────────────────────────────────
self.addEventListener('sync', event => {
  if (event.tag === 'offline-queue-flush') {
    event.waitUntil(
      self.clients.matchAll().then(clients => {
        clients.forEach(client => client.postMessage({ type: 'FLUSH_QUEUE' }));
      })
    );
  }
});
