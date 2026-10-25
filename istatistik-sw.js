// İstatistik uygulamasının servis çalışanı: sadece istatistik sayfasını kapsar, oyuna karışmaz.
// Sayfa önce internetten alınır, internet yoksa en son kaydedilen kopya açılır.
// Sayaç servisine giden istekler hiç kaydedilmez, sayılar hep taze gelir.
const KASA = 'yeralti-istatistik-v1';
const DOSYALAR = ['istatistik.html', 'istatistik.webmanifest', 'istatistik-ikon.svg'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(KASA).then(k => k.addAll(DOSYALAR)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(adlar => Promise.all(adlar.filter(a => a !== KASA).map(a => caches.delete(a))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  e.respondWith(fetch(e.request)
    .then(cevap => {
      const kopya = cevap.clone();
      caches.open(KASA).then(k => k.put(e.request, kopya));
      return cevap;
    })
    .catch(() => caches.match(e.request, { ignoreSearch: true })));
});
