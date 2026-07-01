const CACHE = 'jarvis-v5';
const ASSETS = ['/hud', '/hud/static/style.css', '/hud/static/app.js', '/hud/static/manifest.json'];

self.addEventListener('install',  e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS))));
self.addEventListener('activate', e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))));
self.addEventListener('fetch',    e => {
  if (e.request.url.includes('/ws/') || e.request.url.includes('/stark/')) return;
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});
