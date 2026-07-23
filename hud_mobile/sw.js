// Bump this version string any time hud_mobile assets change structurally
// (e.g. path changes). Old-named caches are deleted on activate, which is
// what actually forces phones to stop serving a stale cached HUD — without
// this bump, a cache-first strategy under a static name would keep serving
// the same snapshot forever, even after server-side fixes.
const CACHE = 'jarvis-v9';
const ASSETS = ['/hud', '/hud/static/style.css', '/hud/static/app.js', '/hud/static/manifest.json'];

self.addEventListener('install', e => {
  self.skipWaiting();  // activate the new SW immediately instead of waiting for all tabs to close
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())  // take control of already-open tabs immediately
  );
});

self.addEventListener('fetch', e => {
  if (e.request.url.includes('/ws/') || e.request.url.includes('/stark/')) return;

  // Network-first for the HTML shell — always get the latest HUD when
  // online, so future changes don't require yet another cache-name bump.
  // Fall back to cache only when offline.
  if (e.request.mode === 'navigate' || e.request.url.endsWith('/hud')) {
    e.respondWith(
      fetch(e.request)
        .then(r => { caches.open(CACHE).then(c => c.put(e.request, r.clone())); return r; })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // Cache-first for static assets (CSS/JS/manifest) — fine to cache since
  // they're versioned by this file's CACHE constant, not by content hash.
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
