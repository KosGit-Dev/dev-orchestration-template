/* オフライン対応 Service Worker: プリキャッシュ + stale-while-revalidate（GET） */
const CACHE = 'wcq-v2';
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

/* キャッシュを即返しつつ、裏で取得してキャッシュを更新する（次回訪問時に最新化） */
self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    caches.open(CACHE).then((cache) =>
      cache.match(e.request, { ignoreSearch: true }).then((hit) => {
        const refresh = fetch(e.request)
          .then((res) => {
            if (res && res.ok) cache.put(e.request, res.clone());
            return res;
          })
          .catch(() => hit); // オフライン時はキャッシュで継続
        return hit || refresh;
      })
    )
  );
});
