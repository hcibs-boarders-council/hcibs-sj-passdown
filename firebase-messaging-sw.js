
importScripts(
    "https://www.gstatic.com/firebasejs/11.10.0/firebase-app-compat.js"
);

importScripts(
    "https://www.gstatic.com/firebasejs/11.10.0/firebase-messaging-compat.js"
);

firebase.initializeApp({
    apiKey: "AIzaSyDpl1NtU2lyyvwalnfWQkWaLnHSRovUhBA",
    authDomain: "hcibs-sj-passdown.firebaseapp.com",
    projectId: "hcibs-sj-passdown",
    storageBucket: "hcibs-sj-passdown.firebasestorage.app",
    messagingSenderId: "1022703955351",
    appId: "1:1022703955351:web:f4cdec8233234064dae8d2",
});

const messaging = firebase.messaging();

messaging.onBackgroundMessage((payload) => {
    // The Django server sends a data-only message.
    const data = payload.data || {};

    const title = data.title || "SJ Passdown";

    const options = {
        body: data.body || "You have a new notification.",
        icon: "/static/img/logo-128.png",
        data: {
            url: data.url || "/",
            item_id: data.item_id || "",
            type: data.type || "",
        },
        tag: data.item_id
            ? `listing-claim-${data.item_id}`
            : "sj-passdown-notification",
    };

    self.registration.showNotification(title, options);
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();

    const targetUrl = new URL(
        event.notification.data?.url || "/",
        self.location.origin
    );

    // Only open pages on the same website.
    if (targetUrl.origin !== self.location.origin) {
        return;
    }

    event.waitUntil(
        clients.openWindow(targetUrl.href)
    );
});
