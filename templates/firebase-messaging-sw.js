
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
    const notification = payload.notification || {};

    const title = notification.title || "SJ Passdown";
    const options = {
        body: notification.body || "You have a new notification.",
        icon: "/static/images/icon-128.png",
        data: payload.data || {},
    };

    self.registration.showNotification(title, options);
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();

    event.waitUntil(
        clients.openWindow(
            event.notification.data.url || "/"
        )
    );
});
