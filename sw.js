// 앱을 고쳐 다시 올릴 때는 버전을 올려 주세요 (예: jh-v10)
const CACHE = 'jh-v18';
const SHELL = ['./', './index.html', './manifest.webmanifest', './icons/icon-192.png', './icons/icon-512.png', './icons/maskable-512.png', './icons/apple-touch-icon.png'];
self.addEventListener('install', e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL.map(u => new Request(u, {cache: 'reload'})))).then(() => self.skipWaiting())));
self.addEventListener('activate', e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener('fetch', e => {
  const req = e.request; if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    e.respondWith(caches.open(CACHE).then(async c => (await c.match(req)) || fetch(req).then(r => { c.put(req, r.clone()); return r; }).catch(() => new Response('', {status: 504}))));
    return;
  }
  if (url.origin !== location.origin) return;   // GitHub·Anthropic·jw.org는 항상 인터넷으로
  // 앱 파일: 브라우저 캐시를 건너뛰고 항상 서버에서 최신본 확인 → 안 되면 저장본
  e.respondWith(fetch(req, {cache: 'no-cache'}).then(r => { if (r.ok && !url.search) { const cp = r.clone(); caches.open(CACHE).then(c => c.put(req, cp)); } return r; })
    .catch(() => caches.match(req, {ignoreSearch: true}).then(r => r || caches.match('./index.html'))));
});
