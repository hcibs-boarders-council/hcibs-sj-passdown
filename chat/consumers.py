
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import transaction
from django.utils import timezone
from django.utils.formats import date_format

from .models import Conversation, Message


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]

        if not user.is_authenticated:
            await self.close(code=4401)
            return

        self.conversation_id = self.scope["url_route"]["kwargs"][
            "conversation_id"
        ]
        self.group_name = f"chat_conversation_{self.conversation_id}"

        if not await self.user_can_access_conversation(
            user, self.conversation_id
        ):
            await self.close(code=4404)
            return

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )
        await self.accept()

    async def disconnect(self, close_code):
        group_name = getattr(self, "group_name", None)

        if group_name:
            await self.channel_layer.group_discard(
                group_name,
                self.channel_name,
            )

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            await self.send_json({
                "type": "error",
                "message": "Invalid message format.",
            })
            return

        if content.get("type") != "message":
            await self.send_json({
                "type": "error",
                "message": "Unsupported message type.",
            })
            return

        client_message_id = content.get("client_message_id")
        if (
            not isinstance(client_message_id, str)
            or not client_message_id
            or len(client_message_id) > 64
        ):
            await self.send_json({
                "type": "error",
                "message": "Invalid message identifier.",
            })
            return

        body = content.get("body")

        if not isinstance(body, str):
            await self.send_json({
                "type": "error",
                "message": "Enter a valid message.",
            })
            return

        body = body.strip()

        if not body:
            await self.send_json({
                "type": "error",
                "message": "Enter a message.",
            })
            return

        if len(body) > 2000:
            await self.send_json({
                "type": "error",
                "message": "Messages cannot exceed 2000 characters.",
            })
            return

        message = await self.create_message(
            self.conversation_id,
            self.scope["user"],
            body,
        )

        if message is None:
            await self.close(code=4404)
            return

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat.message",
                "message": message,
                "client_message_id": client_message_id,
            },
        )

    async def chat_message(self, event):
        await self.send_json({
            "type": "message",
            "message": event["message"],
            "client_message_id": event.get("client_message_id"),
        })

    @database_sync_to_async
    def user_can_access_conversation(self, user, conversation_id):
        return Conversation.objects.for_user(user).filter(
            pk=conversation_id,
        ).exists()

    @database_sync_to_async
    def create_message(self, conversation_id, user, body):
        try:
            with transaction.atomic():
                conversation = Conversation.objects.for_user(user).get(
                    pk=conversation_id,
                )

                message = Message.objects.create(
                    conversation=conversation,
                    sender=user,
                    body=body,
                )

                Conversation.objects.filter(
                    pk=conversation.pk,
                ).update(updated_at=timezone.now())

                conversation.mark_read(user)

                return {
                    "id": message.pk,
                    "sender_id": message.sender_id,
                    "sender_name": user.get_username(),
                    "body": message.body,
                    "created_at": message.created_at.isoformat(),
                    "display_time": date_format(
                        message.created_at,
                        "j M, g:i a",
                    ),
                }
        except Conversation.DoesNotExist:
            return None