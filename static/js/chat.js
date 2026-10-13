/* SJ Passdown — live conversation.

   Messages are sent and received over the conversation WebSocket. Every sent
   message carries a random client id, so retries after a dropped connection
   can never create duplicates (the server reuses the stored message). After
   every (re)connect the page catches up from the messages endpoint, and while
   the socket is down it polls that endpoint and sends over HTTP instead, so
   nothing is missed. Without JavaScript the form posts normally. */
(function () {
    "use strict";

    var root = document.querySelector("[data-chat]");
    if (!root || !window.SJRealtime) return;

    var list = root.querySelector("[data-chat-messages]");
    var form = root.querySelector("[data-chat-form]");
    if (!list || !form) return;

    var textarea = form.querySelector("textarea");
    var sendButton = form.querySelector("[data-chat-send]");
    var hint = form.querySelector("[data-chat-hint]");
    var clientIdInput = form.querySelector("[data-chat-client-id]");
    var statusEl = root.querySelector("[data-chat-status]");
    var csrfInput = form.querySelector("input[name='csrfmiddlewaretoken']");

    var currentUserId = Number(root.getAttribute("data-current-user-id"));
    var pollUrl = root.getAttribute("data-chat-poll-url");
    var readUrl = root.getAttribute("data-chat-read-url");
    var socketPath = root.getAttribute("data-chat-socket-path");

    var rendered = new Set();
    list.querySelectorAll("[data-message-id]").forEach(function (element) {
        rendered.add(Number(element.getAttribute("data-message-id")));
    });
    var latestId = Number(root.getAttribute("data-latest-message-id") || 0);
    var lastReadSent = latestId;
    var pending = new Map();   // client id -> { el, body, timer }
    var pollTimer = null;
    var readTimer = null;
    var statusTimer = null;
    var catchingUp = false;
    var sessionEnded = false;

    // Helpers ---------------------------------------------------------------
    function newClientId() {
        if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
        return "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
    }

    function nearBottom() {
        return list.scrollHeight - list.scrollTop - list.clientHeight < 120;
    }

    function scrollToBottom() {
        list.scrollTop = list.scrollHeight;
    }

    function removeEmptyState() {
        var empty = list.querySelector("[data-chat-empty]");
        if (empty) empty.remove();
    }

    function setStatus(text, tone) {
        window.clearTimeout(statusTimer);
        if (!statusEl) return;
        if (!text) {
            statusEl.hidden = true;
            statusEl.textContent = "";
            return;
        }
        statusEl.textContent = text;
        statusEl.setAttribute("data-tone", tone || "info");
        statusEl.hidden = false;
    }

    function setStatusSoon(text, tone) {
        // Avoid flashing "Reconnecting…" for blips shorter than two seconds.
        window.clearTimeout(statusTimer);
        statusTimer = window.setTimeout(function () { setStatus(text, tone); }, 2000);
    }

    function buildMessage(message, mine) {
        var article = document.createElement("article");
        article.className = "chat-message" + (mine ? " chat-message--mine" : "");

        var meta = document.createElement("p");
        meta.className = "chat-message__sender";
        var who = document.createElement("span");
        who.textContent = mine ? "You" : message.sender_name;
        var time = document.createElement("time");
        if (message.created_at) time.setAttribute("datetime", message.created_at);
        time.textContent = message.display_time || "";
        meta.append(who, time);

        var bodyEl = document.createElement("p");
        bodyEl.className = "chat-message__body";
        bodyEl.textContent = message.body;

        article.append(meta, bodyEl);
        if (message.id) article.setAttribute("data-message-id", String(message.id));
        return article;
    }

    // Keep messages in id order even when catch-up and live events interleave.
    function insertInOrder(element, id) {
        var children = list.querySelectorAll("[data-message-id]");
        for (var index = children.length - 1; index >= 0; index -= 1) {
            if (Number(children[index].getAttribute("data-message-id")) < id) {
                children[index].after(element);
                return;
            }
        }
        var firstPending = list.querySelector(".chat-message.is-pending, .chat-message.is-failed");
        if (children.length === 0 && firstPending) {
            list.insertBefore(element, firstPending);
        } else if (children.length === 0) {
            list.appendChild(element);
        } else {
            list.insertBefore(element, children[0]);
        }
    }

    function remember(message) {
        rendered.add(message.id);
        if (message.id > latestId) latestId = message.id;
    }

    function appendMessage(message) {
        if (!message || !Number.isSafeInteger(message.id) || rendered.has(message.id)) return false;
        var mine = message.sender_id === currentUserId;
        var stick = nearBottom() || mine;
        removeEmptyState();
        insertInOrder(buildMessage(message, mine), message.id);
        remember(message);
        if (stick) scrollToBottom();
        return true;
    }

    // Sending -----------------------------------------------------------------
    function setPendingState(entry, state, text) {
        entry.el.classList.toggle("is-pending", state === "pending");
        entry.el.classList.toggle("is-failed", state === "failed");
        var note = entry.el.querySelector(".chat-message__state");
        if (!note) {
            note = document.createElement("p");
            note.className = "chat-message__state";
            entry.el.appendChild(note);
        }
        note.textContent = "";
        if (state === "pending") {
            note.textContent = text || "Sending…";
        } else if (state === "failed") {
            var label = document.createElement("span");
            label.textContent = text || "Not sent.";
            var retry = document.createElement("button");
            retry.type = "button";
            retry.className = "chat-message__retry";
            retry.textContent = "Retry";
            retry.addEventListener("click", function () { send(entry); });
            note.append(label, " ", retry);
        }
    }

    function send(entry) {
        pending.set(entry.cmid, entry);
        window.clearTimeout(entry.timer);
        if (socket.send({ type: "message", body: entry.body, client_message_id: entry.cmid })) {
            setPendingState(entry, "pending", "Sending…");
            entry.timer = window.setTimeout(function () {
                if (pending.has(entry.cmid)) setPendingState(entry, "failed", "Not sent yet.");
            }, 10000);
            return;
        }
        // Socket down: post it over HTTP instead. If that fails too, the entry
        // stays pending and is re-sent when the socket reconnects.
        sendOverHttp(entry);
    }

    function sendOverHttp(entry) {
        if (entry.httpInFlight) return;
        entry.httpInFlight = true;
        setPendingState(entry, "pending", "Sending…");

        var data = new FormData();
        data.append("body", entry.body);
        data.append("client_message_id", entry.cmid);
        if (csrfInput) data.append("csrfmiddlewaretoken", csrfInput.value);

        window.fetch(form.action, {
            method: "POST",
            credentials: "same-origin",
            headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
            body: data
        }).then(function (response) {
            entry.httpInFlight = false;
            if (response.redirected || response.status === 401 || response.status === 403 || response.status === 404) {
                pending.delete(entry.cmid);
                setPendingState(entry, "failed", "Not sent.");
                endSession();
                return null;
            }
            return response.json().then(function (payload) {
                if (response.ok && payload && payload.message) {
                    confirmSent(entry.cmid, payload.message);
                    return;
                }
                pending.delete(entry.cmid);
                setPendingState(entry, "failed", (payload && payload.error) || "Not sent.");
            });
        }).catch(function () {
            entry.httpInFlight = false;
            if (pending.has(entry.cmid)) setPendingState(entry, "pending", "Waiting for connection…");
        });
    }

    function confirmSent(cmid, message) {
        var entry = pending.get(cmid);
        if (!entry) return false;
        window.clearTimeout(entry.timer);
        pending.delete(cmid);

        if (rendered.has(message.id)) {
            entry.el.remove();
            return true;
        }
        var confirmed = buildMessage(message, true);
        entry.el.replaceWith(confirmed);
        remember(message);
        return true;
    }

    function resendPending() {
        pending.forEach(function (entry) { send(entry); });
    }

    function updateSendState() {
        if (!sendButton || !textarea) return;
        sendButton.disabled = !textarea.value.trim();
    }

    form.addEventListener("submit", function (event) {
        var bodyText = textarea ? textarea.value.trim() : "";
        if (!bodyText) {
            event.preventDefault();
            if (textarea) textarea.focus();
            return;
        }
        if (sessionEnded) {
            // Normal form POST (it leads to the login page); the client id
            // still prevents duplicates.
            if (clientIdInput) clientIdInput.value = newClientId();
            return;
        }
        event.preventDefault();

        var entry = { cmid: newClientId(), body: bodyText, el: null, timer: null };
        entry.el = buildMessage({ body: bodyText, display_time: "" }, true);
        removeEmptyState();
        list.appendChild(entry.el);
        scrollToBottom();
        send(entry);

        textarea.value = "";
        updateSendState();
        textarea.focus();
    });

    if (textarea) {
        textarea.addEventListener("input", updateSendState);
        textarea.addEventListener("keydown", function (event) {
            if (event.key !== "Enter" || event.shiftKey || event.altKey || event.ctrlKey || event.metaKey || event.isComposing) return;
            event.preventDefault();
            if (typeof form.requestSubmit === "function") {
                form.requestSubmit();
            } else {
                form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
            }
        });
    }
    if (hint) hint.hidden = false;
    updateSendState();

    // Read receipts -------------------------------------------------------------
    function markRead() {
        if (document.hidden || sessionEnded || !csrfInput || latestId <= lastReadSent) return;
        var upTo = latestId;
        var data = new FormData();
        data.append("last_message_id", String(upTo));
        window.fetch(readUrl, {
            method: "POST",
            credentials: "same-origin",
            headers: { "X-CSRFToken": csrfInput.value, "X-Requested-With": "XMLHttpRequest" },
            body: data
        }).then(function (response) {
            if (response.ok && upTo > lastReadSent) lastReadSent = upTo;
        }).catch(function () { /* retried on the next message or visibility change */ });
    }

    function scheduleRead() {
        window.clearTimeout(readTimer);
        readTimer = window.setTimeout(markRead, 400);
    }

    document.addEventListener("visibilitychange", function () {
        if (!document.hidden) scheduleRead();
    });

    // Catch-up + fallback polling -------------------------------------------------
    function endSession() {
        sessionEnded = true;
        stopPolling();
        socket.stop();
        setStatus("Your session has ended. Reload the page to keep chatting.", "error");
    }

    function catchUp() {
        if (catchingUp || sessionEnded) return Promise.resolve();
        catchingUp = true;
        var url = new URL(pollUrl, window.location.href);
        url.searchParams.set("after_id", String(latestId));

        return window.fetch(url, {
            credentials: "same-origin",
            headers: { Accept: "application/json" }
        }).then(function (response) {
            if (response.redirected || response.status === 401 || response.status === 403 || response.status === 404) {
                endSession();
                return null;
            }
            if (!response.ok) return null;
            return response.json();
        }).then(function (data) {
            catchingUp = false;
            if (!data || !Array.isArray(data.messages)) return;
            var added = false;
            data.messages.forEach(function (message) {
                if (appendMessage(message) && message.sender_id !== currentUserId) added = true;
            });
            if (added) scheduleRead();
            if (data.messages.length === 100) return catchUp();
        }).catch(function () {
            catchingUp = false;
        });
    }

    function startPolling() {
        if (pollTimer || sessionEnded) return;
        pollTimer = window.setInterval(function () {
            if (!document.hidden) catchUp();
        }, 5000);
    }

    function stopPolling() {
        window.clearInterval(pollTimer);
        pollTimer = null;
    }

    // WebSocket -------------------------------------------------------------------
    var socket = window.SJRealtime.socket(socketPath, {
        open: function () {
            setStatus("");
            stopPolling();
            catchUp().then(resendPending);
        },
        message: function (data) {
            if (data.type === "message" && data.message) {
                var cmid = data.client_message_id;
                if (cmid && confirmSent(cmid, data.message)) {
                    scheduleRead();
                    return;
                }
                if (appendMessage(data.message) && data.message.sender_id !== currentUserId) {
                    scheduleRead();
                }
            } else if (data.type === "error") {
                var entry = data.client_message_id && pending.get(data.client_message_id);
                if (entry) {
                    window.clearTimeout(entry.timer);
                    pending.delete(entry.cmid);
                    setPendingState(entry, "failed", data.message);
                } else if (data.message) {
                    setStatus(data.message, "error");
                }
            }
        },
        close: function () {
            if (sessionEnded) return;
            setStatusSoon(navigator.onLine === false
                ? "You're offline. Messages will send when you're back online."
                : "Reconnecting…", "warning");
            startPolling();
        },
        denied: function () {
            // Closed by the server (e.g. logged out elsewhere). Check over HTTP:
            // still allowed -> reconnect; otherwise catchUp() ends the session.
            catchUp().then(function () {
                if (!sessionEnded) socket.resume();
            });
        }
    });

    window.addEventListener("offline", function () {
        setStatus("You're offline. Messages will send when you're back online.", "warning");
    });

    if (!document.hidden) scrollToBottom();
})();
