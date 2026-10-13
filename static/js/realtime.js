/* SJ Passdown — real-time layer (Django Channels over the existing Redis layer).

   1. SJRealtime.socket(path, handlers): a WebSocket that reconnects with
      exponential backoff + jitter, sends heartbeats to detect dead ("stale")
      connections, and reconnects immediately when the browser comes back
      online or the tab becomes visible.
   2. The per-user notification channel used on every page for logged-in
      students: live unread badges, tab title, chat list updates, a small
      on-page alert and (only if the student opts in) browser notifications.

   Unread numbers always come from the server; nothing is counted client-side.
   If WebSockets are unavailable, badges fall back to polling every 30 s. */
(function () {
    "use strict";

    var HEARTBEAT_MS = 25000;
    var PONG_TIMEOUT_MS = 10000;
    var MAX_BACKOFF_MS = 30000;

    function wsUrl(path) {
        var protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        return protocol + "//" + window.location.host + path;
    }

    function createSocket(path, handlers) {
        handlers = handlers || {};
        var socket = null;
        var attempts = 0;
        var everOpened = false;
        var stopped = false;
        var retryTimer = null;
        var heartbeatTimer = null;
        var pongTimer = null;

        function isOpen() {
            return !!socket && socket.readyState === WebSocket.OPEN;
        }

        function isActive() {
            return !!socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING);
        }

        function send(data) {
            if (!isOpen()) return false;
            try {
                socket.send(JSON.stringify(data));
                return true;
            } catch (error) {
                return false;
            }
        }

        function clearHeartbeat() {
            window.clearInterval(heartbeatTimer);
            window.clearTimeout(pongTimer);
            heartbeatTimer = null;
            pongTimer = null;
        }

        function startHeartbeat() {
            clearHeartbeat();
            heartbeatTimer = window.setInterval(function () {
                if (!send({ type: "ping" })) return;
                window.clearTimeout(pongTimer);
                pongTimer = window.setTimeout(function () {
                    // No pong: the connection is half-open. Drop it and reconnect.
                    if (socket) socket.close(4000, "heartbeat timeout");
                }, PONG_TIMEOUT_MS);
            }, HEARTBEAT_MS);
        }

        function schedule() {
            if (stopped) return;
            attempts += 1;
            var base = Math.min(MAX_BACKOFF_MS, 1000 * Math.pow(2, Math.min(attempts - 1, 5)));
            var delay = base * (0.7 + Math.random() * 0.6);
            if (document.hidden) delay = Math.max(delay, 15000);
            window.clearTimeout(retryTimer);
            retryTimer = window.setTimeout(connect, delay);
            if (handlers.retrying) handlers.retrying(attempts, everOpened);
        }

        function connect() {
            if (stopped || isActive()) return;
            window.clearTimeout(retryTimer);
            try {
                socket = new WebSocket(wsUrl(path));
            } catch (error) {
                socket = null;
                schedule();
                return;
            }

            socket.addEventListener("open", function () {
                attempts = 0;
                everOpened = true;
                startHeartbeat();
                if (handlers.open) handlers.open();
            });

            socket.addEventListener("message", function (event) {
                var data;
                try {
                    data = JSON.parse(event.data);
                } catch (error) {
                    return;
                }
                if (!data || typeof data !== "object") return;
                if (data.type === "pong") {
                    window.clearTimeout(pongTimer);
                    return;
                }
                if (handlers.message) handlers.message(data);
            });

            socket.addEventListener("close", function (event) {
                clearHeartbeat();
                socket = null;
                if (handlers.close) handlers.close(event);
                if (stopped) return;
                // Closed by the server after connecting: logged out or no access.
                if (event.code === 4401 || event.code === 4404) {
                    if (handlers.denied) {
                        handlers.denied(event.code);
                    } else {
                        stopped = true;
                    }
                    return;
                }
                schedule();
            });
        }

        function reconnectNow() {
            if (stopped || isActive()) return;
            attempts = 0;
            connect();
        }

        window.addEventListener("online", reconnectNow);
        document.addEventListener("visibilitychange", function () {
            if (!document.hidden) reconnectNow();
        });

        connect();

        return {
            send: send,
            isOpen: isOpen,
            reconnectNow: reconnectNow,
            stop: function () {
                stopped = true;
                window.clearTimeout(retryTimer);
                clearHeartbeat();
                if (socket) socket.close(1000);
            },
            resume: function () {
                stopped = false;
                reconnectNow();
            }
        };
    }

    window.SJRealtime = { socket: createSocket, wsUrl: wsUrl };

    // ---------------------------------------------------------------------
    // Notification channel (logged-in pages only)
    // ---------------------------------------------------------------------

    var body = document.body;
    var socketPath = body.getAttribute("data-realtime-url");
    if (!socketPath || !("WebSocket" in window)) return;

    var unreadUrl = body.getAttribute("data-unread-url");
    var currentUserId = Number(body.getAttribute("data-user-id"));
    var openConversationId = Number(body.getAttribute("data-open-conversation-id") || 0);
    var iconUrl = body.getAttribute("data-icon-url");
    var baseTitle = document.title.replace(/^\(\d+\+?\)\s+/, "");
    var pollTimer = null;
    var sessionEnded = false;

    function viewingConversation(conversationId) {
        return openConversationId && conversationId === openConversationId && !document.hidden;
    }

    function renderTotal(total) {
        total = Math.max(0, Number(total) || 0);
        var label = total > 99 ? "99+" : String(total);
        document.querySelectorAll("[data-unread-count]").forEach(function (badge) {
            var value = badge.querySelector("[data-unread-value]");
            if (value) value.textContent = label;
            badge.hidden = total < 1;
        });
        document.querySelectorAll("[data-unread-dot]").forEach(function (dot) {
            dot.hidden = total < 1;
        });
        document.title = total > 0 ? "(" + label + ") " + baseTitle : baseTitle;
    }

    // While a conversation is open and visible, its new messages are being read
    // as they arrive, so they shouldn't flash up in the badge.
    function visibleTotal(data) {
        var total = Number(data.unread_total) || 0;
        if (viewingConversation(data.conversation_id)) {
            total -= Number(data.conversation_unread) || 0;
        }
        return total;
    }

    // Chat list (on /chat/) ------------------------------------------------
    function truncate(text, length) {
        text = String(text || "");
        return text.length > length ? text.slice(0, length - 1) + "…" : text;
    }

    function shortDate(message) {
        return String(message.display_time || "").split(",")[0];
    }

    function setRowUnread(row, count) {
        var badge = row.querySelector("[data-unread]");
        if (badge) {
            var value = badge.querySelector("[data-unread-value]");
            if (value) value.textContent = String(count);
            badge.hidden = !(count > 0);
        }
        row.classList.toggle("has-unread", count > 0);
    }

    function buildRow(data) {
        var row = document.createElement("a");
        row.className = "chat-list__item";
        row.href = data.conversation_url;
        row.setAttribute("data-conversation-row", "");
        row.setAttribute("data-conversation-id", String(data.conversation_id));

        var avatar = document.createElement("span");
        avatar.className = "avatar";
        avatar.setAttribute("aria-hidden", "true");
        avatar.textContent = (data.counterpart_name || "?").charAt(0).toUpperCase();

        var content = document.createElement("span");
        content.className = "chat-list__content";

        var top = document.createElement("span");
        top.className = "chat-list__top";
        var name = document.createElement("strong");
        name.className = "chat-list__name";
        name.textContent = data.counterpart_name;
        var time = document.createElement("time");
        time.className = "chat-list__time";
        time.setAttribute("data-time", "");
        top.append(name, time);

        var itemTitle = document.createElement("span");
        itemTitle.className = "chat-list__item-title";
        itemTitle.textContent = data.item_title;

        var bottom = document.createElement("span");
        bottom.className = "chat-list__bottom";
        var preview = document.createElement("span");
        preview.className = "chat-list__preview";
        preview.setAttribute("data-preview", "");
        var badge = document.createElement("span");
        badge.className = "chat-unread";
        badge.setAttribute("data-unread", "");
        badge.hidden = true;
        var value = document.createElement("span");
        value.setAttribute("data-unread-value", "");
        var hidden = document.createElement("span");
        hidden.className = "visually-hidden";
        hidden.textContent = " unread";
        badge.append(value, hidden);
        bottom.append(preview, badge);

        content.append(top, itemTitle, bottom);
        row.append(avatar, content);
        return row;
    }

    function updateChatList(data) {
        var list = document.querySelector("[data-chat-list]");
        if (!list) return false;

        var row = list.querySelector('[data-conversation-id="' + data.conversation_id + '"]');
        var item;
        if (!row) {
            row = buildRow(data);
            item = document.createElement("li");
            item.appendChild(row);
            var empty = document.querySelector("[data-chat-empty]");
            if (empty) empty.remove();
            list.hidden = false;
        } else {
            item = row.closest("li") || row;
        }
        list.insertBefore(item, list.firstElementChild);

        var message = data.message || {};
        var preview = row.querySelector("[data-preview]");
        if (preview) {
            preview.textContent = (message.sender_id === currentUserId ? "You: " : "") + truncate(message.body, 90);
        }
        var time = row.querySelector("[data-time]");
        if (time && message.created_at) {
            time.setAttribute("datetime", message.created_at);
            time.textContent = shortDate(message);
        }
        setRowUnread(row, Number(data.conversation_unread) || 0);

        if (message.sender_id !== currentUserId) {
            row.classList.remove("is-new");
            void row.offsetWidth; // restart the highlight animation
            row.classList.add("is-new");
        }
        return true;
    }

    function applyRead(data) {
        var row = document.querySelector('[data-chat-list] [data-conversation-id="' + data.conversation_id + '"]');
        if (row) setRowUnread(row, Number(data.conversation_unread) || 0);
    }

    // On-page alert ----------------------------------------------------------
    function showToast(data) {
        var region = document.querySelector("[data-toast-region]");
        if (!region) return;

        var toast = document.createElement("div");
        toast.className = "toast";

        var link = document.createElement("a");
        link.className = "toast__link";
        link.href = data.conversation_url;
        var title = document.createElement("strong");
        title.textContent = "New message from " + data.counterpart_name;
        var meta = document.createElement("span");
        meta.textContent = truncate(data.item_title, 60);
        link.append(title, meta);

        var close = document.createElement("button");
        close.type = "button";
        close.className = "toast__close";
        close.setAttribute("aria-label", "Dismiss");
        close.textContent = "×";
        close.addEventListener("click", function () { toast.remove(); });

        toast.append(link, close);
        region.appendChild(toast);

        var timer = window.setTimeout(function () { toast.remove(); }, 7000);
        toast.addEventListener("mouseenter", function () { window.clearTimeout(timer); });
        toast.addEventListener("focusin", function () { window.clearTimeout(timer); });

        while (region.children.length > 3) region.firstElementChild.remove();
    }

    // Browser notifications (opt-in only) -------------------------------------
    function notificationsSupported() {
        return "Notification" in window && window.isSecureContext !== false;
    }

    function showBrowserNotification(data) {
        if (!notificationsSupported() || Notification.permission !== "granted" || !document.hidden) return;
        try {
            // Sender and item only — message text stays private on shared screens.
            var notification = new Notification("New message from " + data.counterpart_name, {
                body: "About: " + data.item_title,
                tag: "sj-chat-" + data.conversation_id,
                icon: iconUrl || undefined
            });
            notification.onclick = function () {
                window.focus();
                window.location.href = data.conversation_url;
                notification.close();
            };
        } catch (error) {
            /* Some browsers only allow notifications from a service worker. */
        }
    }

    function setupAlertsControl() {
        var box = document.querySelector("[data-alerts]");
        if (!box || !notificationsSupported()) return;
        var button = box.querySelector("[data-alerts-enable]");
        var status = box.querySelector("[data-alerts-status]");

        function render() {
            box.hidden = false;
            var permission = Notification.permission;
            if (button) button.hidden = permission !== "default";
            if (status) {
                status.textContent = permission === "granted"
                    ? "Message alerts are on in this browser while SJ Passdown is open."
                    : permission === "denied"
                        ? "Message alerts are blocked in your browser settings."
                        : "";
            }
        }

        if (button) {
            button.addEventListener("click", function () {
                var result = Notification.requestPermission(render);
                if (result && typeof result.then === "function") result.then(render);
            });
        }
        render();
    }

    // Fallback polling ------------------------------------------------------
    function pollUnread() {
        if (!unreadUrl || document.hidden || sessionEnded) return Promise.resolve(true);
        return window.fetch(unreadUrl, {
            credentials: "same-origin",
            headers: { Accept: "application/json" }
        }).then(function (response) {
            if (response.status === 401) {
                endSession();
                return false;
            }
            if (!response.ok) return true;
            return response.json().then(function (data) {
                renderTotal(data.unread_total);
                return true;
            });
        }).catch(function () {
            return true;
        });
    }

    function startPolling() {
        if (pollTimer || sessionEnded) return;
        pollTimer = window.setInterval(pollUnread, 30000);
    }

    function stopPolling() {
        window.clearInterval(pollTimer);
        pollTimer = null;
    }

    function endSession() {
        sessionEnded = true;
        stopPolling();
        if (channel) channel.stop();
    }

    // Wire it up -------------------------------------------------------------
    var channel = createSocket(socketPath, {
        open: function () {
            stopPolling();
        },
        message: function (data) {
            if (data.type === "hello") {
                renderTotal(data.unread_total);
            } else if (data.type === "message") {
                renderTotal(visibleTotal(data));
                var onList = updateChatList(data);
                var fromOther = data.message && data.message.sender_id !== currentUserId;
                if (fromOther && !viewingConversation(data.conversation_id)) {
                    if (!onList && !document.hidden) showToast(data);
                    showBrowserNotification(data);
                }
            } else if (data.type === "read") {
                renderTotal(visibleTotal(data));
                applyRead(data);
            }
        },
        close: function () {
            startPolling();
        },
        retrying: function (attempts, everOpened) {
            // Repeated failures before ever connecting: check the session is
            // still valid instead of retrying forever.
            if (!everOpened && attempts === 3) pollUnread();
        },
        denied: function () {
            // Another tab logged out, or this session ended. Confirm over HTTP.
            pollUnread().then(function (stillLoggedIn) {
                if (stillLoggedIn && channel) channel.resume();
            });
        }
    });

    window.SJRealtime.notifications = channel;
    setupAlertsControl();
})();
