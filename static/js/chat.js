
(() => {
    const thread = document.querySelector('.chat-thread[data-chat-poll-url]');

    if (!thread) {
        return;
    }

    const messagesContainer = thread.querySelector('.chat-thread__messages');
    const composeForm = thread.querySelector('.chat-compose');
    const currentUserId = Number(thread.dataset.currentUserId);
    const pollUrl = thread.dataset.chatPollUrl;
    const markReadUrl = thread.dataset.chatReadUrl;

    if (!messagesContainer || !composeForm || !pollUrl || !markReadUrl) {
        return;
    }

    let latestMessageId = Number(
        messagesContainer.dataset.latestMessageId || 0
    );
    let polling = false;
    let stopped = false;

    function isNearBottom() {
        return (
            messagesContainer.scrollHeight -
            messagesContainer.scrollTop -
            messagesContainer.clientHeight
        ) < 100;
    }

    function createMessage(message) {
        const article = document.createElement('article');
        article.className = 'chat-message';

        if (message.sender_id === currentUserId) {
            article.classList.add('chat-message--mine');
        }

        const sender = document.createElement('p');
        sender.className = 'chat-message__sender';

        const senderName = document.createElement('span');
        senderName.textContent =
            message.sender_id === currentUserId
                ? 'You'
                : message.sender_name;

        const time = document.createElement('time');
        time.dateTime = message.created_at;
        time.textContent = message.display_time;

        sender.append(senderName, time);

        const body = document.createElement('p');
        body.className = 'chat-message__body';
        body.textContent = message.body;

        article.append(sender, body);

        return article;
    }

    async function markRead() {
        if (document.hidden || stopped) {
            return;
        }

        const csrfInput = composeForm.querySelector(
            'input[name="csrfmiddlewaretoken"]'
        );

        if (!csrfInput) {
            return;
        }

        try {
            await fetch(markReadUrl, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': csrfInput.value,
                    'X-Requested-With': 'XMLHttpRequest',
                },
            });
        } catch {
            // A later polling cycle can retry.
        }
    }

    async function pollMessages() {
        if (polling || stopped || document.hidden) {
            return;
        }

        polling = true;

        try {
            const url = new URL(pollUrl, window.location.origin);
            url.searchParams.set('after_id', String(latestMessageId));

            const response = await fetch(url, {
                credentials: 'same-origin',
                headers: {
                    Accept: 'application/json',
                },
            });

            if (!response.ok) {
                if (
                    response.status === 401 ||
                    response.status === 403 ||
                    response.status === 404
                ) {
                    stopped = true;
                }
                return;
            }

            const data = await response.json();

            if (!Array.isArray(data.messages)) {
                return;
            }

            const shouldScroll = isNearBottom();

            for (const message of data.messages) {
                if (
                    !Number.isSafeInteger(message.id) ||
                    message.id <= latestMessageId
                ) {
                    continue;
                }

                const emptyMessage = messagesContainer.querySelector(
                    '.chat-thread__empty'
                );

                if (emptyMessage) {
                    emptyMessage.remove();
                }

                messagesContainer.appendChild(createMessage(message));
                latestMessageId = message.id;
            }

            messagesContainer.dataset.latestMessageId =
                String(latestMessageId);

            if (data.messages.length > 0) {
                await markRead();

                if (shouldScroll) {
                    messagesContainer.scrollTop =
                        messagesContainer.scrollHeight;
                }
            }
        } catch {
            // Temporary network errors are retried on the next poll.
        } finally {
            polling = false;
        }
    }

    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            pollMessages();
        }
    });

    if (!document.hidden) {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    window.setInterval(pollMessages, 3000);
})();