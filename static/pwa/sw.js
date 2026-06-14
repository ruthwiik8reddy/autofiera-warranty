/* X-PPF service worker — app shell + runtime caching */
const VERSION = 'xppf-v1';
const SHELL = [
  '/', '/products', '/about', '/login', '/offline',
  '/static/css/tokens.css', '/static/css/app.css',
  '/static/img/xppf-logo.svg', '/static/pwa/icon-192.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return; // leave CDN (GSAP) to the network

  // Pages: network-first (keeps logged-in content fresh), fall back to cache/offline
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req)
        .then((res) => { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); return res; })
        .catch(() => caches.match(req).then((r) => r || caches.match('/offline')))
    );
    return;
  }

  // Static assets (css/js/images/frames/videos): cache-first, then network + cache
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); return res;
      }))
    );
  }
});
