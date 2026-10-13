import time
from collections import deque

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from . import services
from .models import Conversation

# Per-connection flood protection for sending messages.
RATE_LIMIT_MESSAGES = 10
RATE_LIMIT_WINDOW_SECONDS = 10


class SessionAwareConsumer(AsyncJsonWebsocketConsumer):
    """Base consumer: joins the user's session group so logout can close it,
    and answers heartbeat pings."""

    joined_groups = ()

    async def join(self, *groups):
        self.joined_groups = tuple(groups)
        for group in self.joined_groups:
            await self.channel_layer.group_add(group, self.channel_name)

    async def disconnect(self, close_code):
        for group in self.joined_groups:
            await self.channel_layer.group_discard(group, self.channel_name)

    def session_key(self):
        session = self.scope.get('session')
        return getattr(session, 'session_key', None)

    async def session_ended(self, event):
        # Only close sockets opened with the session that logged out; the same
        # user's other devices stay connected.
        if event.get('session_key') in (None, self.session_key()):
            await self.close(code=4401)

    async def reply_to_ping(self, content):
        if isinstance(content, dict) and content.get('type') == 'ping':
            await self.send_json({'type': 'pong'})
            return True
        return False


class ChatConsumer(SessionAwareConsumer):
    """One open conversation: receives its messages and sends new ones."""

    async def connect(self):
        user = self.scope["user"]

        if not user.is_authenticated:
            await self.close(code=4401)
            return

        self.conversation_id = self.scope["url_route"]["kwargs"]["conversation_id"]
        self.group_name = services.conversation_group(self.conversation_id)

        if not await self.user_can_access_conversation(user, self.conversation_id):
            await self.close(code=4404)
            return

        self.recent_sends = deque()
        await self.join(self.group_name, services.session_group(user.pk))
        await self.accept()

    async def receive_json(self, content, **kwargs):
        if await self.reply_to_ping(content):
            return

        if not isinstance(content, dict):
            await self.send_error("Invalid message format.")
            return

        if content.get("type") != "message":
            await self.send_error("Unsupported message type.")
            return

        client_message_id = content.get("client_message_id")
        if not services.is_valid_client_message_id(client_message_id):
            await self.send_error("Invalid message identifier.")
            return

        body = content.get("body")
        if not isinstance(body, str):
            await self.send_error("Enter a valid message.", client_message_id)
            return

        body = body.strip()
        if not body:
            await self.send_error("Enter a message.", client_message_id)
            return

        if len(body) > 2000:
            await self.send_error("Messages cannot exceed 2000 characters.", client_message_id)
            return

        if self.is_rate_limited():
            await self.send_error(
                "You're sending messages too quickly. Please wait a moment.",
                client_message_id,
            )
            return

        result = await self.create_message(
            self.conversation_id,
            self.scope["user"],
            body,
            client_message_id,
        )

        if result is None:
            # The user no longer has access to this conversation.
            await self.close(code=4404)
            return

        if result == "conflict":
            await self.send_error("Invalid message identifier.", client_message_id)
            return

        message_event, events, created = result
        if created:
            await services.asend_events(self.channel_layer, events)
        else:
            # A retried send: re-confirm to this socket only, no duplicate broadcast.
            await self.send_json(message_event)

    async def send_error(self, text, client_message_id=None):
        payload = {"type": "error", "message": text}
        if client_message_id:
            payload["client_message_id"] = client_message_id
        await self.send_json(payload)

    def is_rate_limited(self):
        now = time.monotonic()
        while self.recent_sends and now - self.recent_sends[0] > RATE_LIMIT_WINDOW_SECONDS:
            self.recent_sends.popleft()
        if len(self.recent_sends) >= RATE_LIMIT_MESSAGES:
            return True
        self.recent_sends.append(now)
        return False

    async def chat_message(self, event):
        await self.send_json({
            "type": "message",
            "message": event["message"],
            "client_message_id": event.get("client_message_id"),
        })

    @database_sync_to_async
    def user_can_access_conversation(self, user, conversation_id):
        return Conversation.objects.for_user(user).filter(pk=conversation_id).exists()

    @database_sync_to_async
    def create_message(self, conversation_id, user, body, client_message_id):
        try:
            # Re-checked on every message, so access removed mid-connection is honoured.
            conversation = Conversation.objects.for_user(user).get(pk=conversation_id)
        except Conversation.DoesNotExist:
            return None

        try:
            message, created = services.create_message(
                conversation=conversation,
                sender=user,
                body=body,
                client_message_id=client_message_id,
            )
        except services.ClientMessageIdConflict:
            return "conflict"

        message_event = {
            "type": "message",
            "message": services.serialize_message(message, sender_name=user.get_username()),
            "client_message_id": message.client_message_id,
        }
        events = services.message_events(message) if created else []
        return message_event, events, created


class NotificationConsumer(SessionAwareConsumer):
    """Per-user channel used by every page: unread counts, chat list updates
    and alerts. Only ever receives events about the connected user."""

    async def connect(self):
        user = self.scope["user"]

        if not user.is_authenticated:
            await self.close(code=4401)
            return

        await self.join(services.user_group(user.pk), services.session_group(user.pk))
        await self.accept()
        # Initial sync: covers anything that happened while disconnected.
        total = await database_sync_to_async(services.unread_total)(user)
        await self.send_json({"type": "hello", "unread_total": total})

    async def receive_json(self, content, **kwargs):
        if await self.reply_to_ping(content):
            return
        await self.send_json({"type": "error", "message": "Unsupported message type."})

    async def notify_message(self, event):
        payload = {key: value for key, value in event.items() if key != "type"}
        await self.send_json({"type": "message", **payload})

    async def notify_read(self, event):
        payload = {key: value for key, value in event.items() if key != "type"}
        await self.send_json({"type": "read", **payload})
