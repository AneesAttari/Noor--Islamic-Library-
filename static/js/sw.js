/* Minimal service worker: caches the app shell (static assets) so the
   library opens from the home screen even on a flaky connection. Pages and
   PDFs always come from the network — never stale content. */
var CACHE = 'maktaba-shell-v1';

self.addEventListener('install', function (event) {
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k !== CACHE; })
        .map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (event) {
  var request = event.request;
  if (request.method !== 'GET') return;
  var url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // only the static shell is cached; everything else goes straight to network
  if (url.pathname.indexOf('/static/') === 0) {
    event.respondWith(
      caches.open(CACHE).then(function (cache) {
        return cache.match(request).then(function (hit) {
          if (hit) return hit;
          return fetch(request).then(function (response) {
            if (response && response.ok) cache.put(request, response.clone());
            return response;
          });
        });
      })
    );
  }
});
