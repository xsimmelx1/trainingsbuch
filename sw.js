// Service Worker: Offline-Cache für die App-Hülle und Bilder, Empfang der Push-Erinnerungen.
const CACHE = "tb-v170";
const SHELL = ["./", "index.html", "recipes.json", "mealplan.json", "prices.json", "prodimg.json", "videos.json", "coach.json", "manifest.webmanifest", "icon-192.png", "badge-96.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL.map(u => new Request(u, {cache: "reload"})))).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.includes("/img/")) {
    // Bilder: erst Cache, dann Netz
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request).then(res => { if (res.ok) { const cp = res.clone(); caches.open(CACHE).then(c => c.put(e.request, cp)); } return res; })));
    return;
  }
  // App-Hülle: erst Netz (damit Updates ankommen), offline aus dem Cache
  e.respondWith(fetch(e.request, {cache: "no-cache"}).then(res => { if (res.ok) { const cp = res.clone(); caches.open(CACHE).then(c => c.put(e.request, cp)); } return res; }).catch(() => caches.match(e.request).then(r => r || (e.request.mode === "navigate" ? caches.match("index.html") : Response.error()))));
});

self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = {body: e.data && e.data.text()}; }
  e.waitUntil(self.registration.showNotification(d.title || "Trainingsbuch", {
    body: d.body || "",
    icon: "icon-192.png",
    badge: "badge-96.png",
    tag: d.tag || undefined,
    renotify: !!d.tag,
    data: {url: d.url || "./"},
    actions: d.action ? [{action: "open", title: d.action}] : []
  }));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  const target = new URL(e.notification.data && e.notification.data.url || "./", self.registration.scope).href;
  e.waitUntil(self.clients.matchAll({type: "window", includeUncontrolled: true}).then(list => {
    for (const c of list) {
      if (c.url.startsWith(self.registration.scope)) { c.postMessage({url: target}); return c.focus(); }
    }
    return self.clients.openWindow(target);
  }));
});
