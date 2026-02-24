// Install event
self.addEventListener("install", event => {
  self.skipWaiting(); // Activate worker immediately
});

// Activate event
self.addEventListener("activate", event => {
  clients.claim(); // Control all pages
});

// Fetch event (basic proxy for now)
self.addEventListener("fetch", event => {
  event.respondWith(fetch(event.request));
});
self.addEventListener("push", event => {
  const data = event.data ? event.data.json() : {};
  const title = data.title || "SmartPOS";
  const options = {
    body: data.body || "",
    icon: "/static/icons/icon-192.png",
    badge: "/static/icons/icon-192.png",
    data: data.url || "/"
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  const url = event.notification.data || "/";
  event.waitUntil(clients.openWindow(url));
});
