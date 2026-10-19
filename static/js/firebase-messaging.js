
import {
    initializeApp,
    getApps,
    getApp,
} from "https://www.gstatic.com/firebasejs/11.10.0/firebase-app.js";

import {
    getMessaging,
    getToken,
    onMessage,
    isSupported,
} from "https://www.gstatic.com/firebasejs/11.10.0/firebase-messaging.js";

const firebaseConfig = {
    apiKey: "AIzaSyDpl1NtU2lyyvwalnfWQkWaLnHSRovUhBA",
    authDomain: "hcibs-sj-passdown.firebaseapp.com",
    projectId: "hcibs-sj-passdown",
    storageBucket: "hcibs-sj-passdown.firebasestorage.app",
    messagingSenderId: "1022703955351",
    appId: "1:1022703955351:web:f4cdec8233234064dae8d2",
};

const VAPID_PUBLIC_KEY =
    "BHwnfHfwjeFDJHPo_D66GpFzjX3j7IjqOaGkpBY5hfvFis9AhoxRCkKEZpMWzLUZjzRbrOWIclwIqwJTjyN-KMU";

const app = getApps().length ? getApp() : initializeApp(firebaseConfig);

let messagingInstance = null;
let foregroundListenerRegistered = false;

function getCsrfToken() {
    const cookie = document.cookie
        .split("; ")
        .find((row) => row.startsWith("csrftoken="));

    return cookie
        ? decodeURIComponent(cookie.substring("csrftoken=".length))
        : null;
}

async function saveTokenToDjango(token) {
    const csrfToken = getCsrfToken();

    if (!csrfToken) {
        throw new Error(
            "The CSRF token is missing. Refresh the page and try again."
        );
    }

    const response = await fetch("/notifications/save-token/", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken,
        },
        credentials: "same-origin",
        body: JSON.stringify({ token }),
    });

    let result;

    try {
        result = await response.json();
    } catch {
        throw new Error(
            "The server returned an unexpected response while saving the token."
        );
    }

    if (!response.ok || !result.ok) {
        throw new Error(
            result.error || "Django could not save the notification token."
        );
    }
}

function registerForegroundListener(messaging) {
    if (foregroundListenerRegistered) {
        return;
    }

    foregroundListenerRegistered = true;

    onMessage(messaging, (payload) => {
        const title =
            payload.notification?.title || "SJ Passdown";

        const body =
            payload.notification?.body ||
            "You have a new notification.";

        // Foreground notifications are shown while the website is open.
        alert(`${title}\n${body}`);
    });
}

async function enableNotifications() {
    const button = document.getElementById("enable-notifications");

    if (button) {
        button.disabled = true;
    }

    try {
        if (
            !("Notification" in window) ||
            !("serviceWorker" in navigator)
        ) {
            alert(
                "This browser does not support web push notifications."
            );
            return;
        }

        if (!(await isSupported())) {
            alert(
                "Firebase Messaging is not supported in this browser."
            );
            return;
        }

        if (!window.isSecureContext) {
            alert(
                "Notifications require HTTPS or localhost. Open the secure website and try again."
            );
            return;
        }

        const permission = await Notification.requestPermission();

        if (permission !== "granted") {
            alert(
                "Notifications were not enabled. You can change this in your browser settings."
            );
            return;
        }

        const registration =
            await navigator.serviceWorker.register(
                "/firebase-messaging-sw.js"
            );

        await navigator.serviceWorker.ready;

        messagingInstance = getMessaging(app);

        const token = await getToken(messagingInstance, {
            vapidKey: VAPID_PUBLIC_KEY,
            serviceWorkerRegistration: registration,
        });

        if (!token) {
            throw new Error(
                "Firebase did not generate a notification token. Please try again."
            );
        }

        // Save this browser/device's token to the signed-in Django account.
        await saveTokenToDjango(token);

        registerForegroundListener(messagingInstance);

        console.log("FCM notification token saved successfully.");

        alert(
            "Notifications are enabled on this device!"
        );
    } catch (error) {
        console.error(
            "Could not enable notifications:",
            error
        );

        alert(
            `Could not enable notifications: ${
                error.message || "Check the browser console for details."
            }`
        );
    } finally {
        if (button) {
            button.disabled = false;
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const button = document.getElementById(
        "enable-notifications"
    );

    if (button) {
        button.addEventListener(
            "click",
            enableNotifications
        );
    }
});
