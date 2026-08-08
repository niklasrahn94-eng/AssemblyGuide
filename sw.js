/* Assembly Guide service worker.
   Everything is precached on install, so the tool works with no connection at all
   once it has been loaded once on shop wifi.

   Bump CACHE when any precached file changes — that is what triggers the update. */

/* v2: the progress store key changed and the recut work landed in index.html.
   Bump again for the assembly_data.js regeneration if that ships as a second
   deploy - an unbumped cache serves the old data forever on a bad-wifi phone. */
const CACHE = 'assembly-guide-v2';

const PRECACHE = [
  './',
  './index.html',
  './assembly_data.js',
  './three.min.js',
  './OrbitControls.js',
  './manifest.webmanifest',
  './icon-180.png',
  './icon-192.png',
  './icon-512.png',
  './icon-maskable-512.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE)
      // addAll is all-or-nothing; add individually so one 404 can't leave us
      // with no cache at all in the workshop.
      .then((c) => Promise.all(PRECACHE.map((u) => c.add(u).catch(() => null))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('message', (e) => {
  if (e.data === 'skipWaiting') self.skipWaiting();
});

/* Cache first — the data never changes behind our back, and being instant and
   offline matters more here than being fresh. A background revalidate picks up
   a new deploy for the next launch. */
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  if (new URL(req.url).origin !== self.location.origin) return;

  e.respondWith(
    caches.match(req).then((hit) => {
      const net = fetch(req).then((res) => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      }).catch(() => hit);
      return hit || net;
    })
  );
});
