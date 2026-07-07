/* オフライン対応 Service Worker: 全アセットをプリキャッシュする（キャッシュファースト） */
const CACHE = 'wcq-v1';
const ASSETS = [
  './index.html',
  './manifest.webmanifest',
  './css/style.css',
  './js/util.js', './js/storage.js', './js/quiz.js', './js/map.js',
  './js/sensory.js', './js/essay.js', './js/stats.js', './js/app.js',
  './data/worldmap.js', './data/questions.js', './data/essays.js',
  './data/mapdata.js', './data/sensory.js',
  './icons/icon-180.png', './icons/icon-192.png', './icons/icon-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  e.respondWith(
    caches.match(e.request, { ignoreSearch: true }).then((hit) => hit || fetch(e.request))
  );
});
