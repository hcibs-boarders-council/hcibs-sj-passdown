from asgiref.sync import async_to_sync, sync_to_async
from channels.layers import get_channel_layer
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from channels.layers import InMemoryChannelLayer
from django.test import TransactionTestCase, override_settings
from chat.routing import websocket_urlpatterns

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from listings.models import Item
from .context_processors import chat_unread_count
from .models import Conversation, ConversationReadState, Message

from channels.auth import AuthMiddlewareStack
from django.conf import settings

User = get_user_model()


class ChatViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username='owner',
            password='TestPassword123!',
        )
        cls.requester = User.objects.create_user(
            username='requester',
            password='TestPassword123!',
        )
        cls.outsider = User.objects.create_user(
            username='outsider',
            password='TestPassword123!',
        )

        cls.item = Item.objects.create(
            owner=cls.owner,
            title='Test textbook',
            description='A textbook for testing chat.',
            category=Item.Category.BOOKS,
        )

        cls.conversation = Conversation.objects.create(
            item=cls.item,
            owner=cls.owner,
            requester=cls.requester,
        )

    def test_anonymous_user_is_redirected_from_chat_list(self):
        response = self.client.get(reverse('chat:conversation_list'))

        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_participant_can_view_conversation(self):
        self.client.force_login(self.requester)

        response = self.client.get(
            reverse(
                'chat:conversation_detail',
                args=[self.conversation.pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test textbook')

    def test_outsider_cannot_view_conversation(self):
        self.client.force_login(self.outsider)

        response = self.client.get(
            reverse(
                'chat:conversation_detail',
                args=[self.conversation.pk],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_participant_can_send_message(self):
        self.client.force_login(self.requester)

        response = self.client.post(
            reverse(
                'chat:conversation_detail',
                args=[self.conversation.pk],
            ),
            {'body': '  Hello, is this available?  '},
        )

        self.assertRedirects(
            response,
            reverse(
                'chat:conversation_detail',
                args=[self.conversation.pk],
            ),
        )

        message = Message.objects.get(conversation=self.conversation)

        self.assertEqual(message.sender, self.requester)
        self.assertEqual(message.body, 'Hello, is this available?')

    def test_outsider_cannot_send_message(self):
        self.client.force_login(self.outsider)

        response = self.client.post(
            reverse(
                'chat:conversation_detail',
                args=[self.conversation.pk],
            ),
            {'body': 'This should not be saved.'},
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            Message.objects.filter(
                conversation=self.conversation,
                body='This should not be saved.',
            ).exists()
        )

    def test_get_cannot_start_conversation(self):
        self.client.force_login(self.requester)

        response = self.client.get(
            reverse('chat:start_conversation', args=[self.item.pk])
        )

        self.assertEqual(response.status_code, 405)
        self.assertEqual(Conversation.objects.count(), 1)

    def test_owner_cannot_start_conversation_with_own_item(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('chat:start_conversation', args=[self.item.pk])
        )

        self.assertRedirects(
            response,
            reverse('item_detail', args=[self.item.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(Conversation.objects.count(), 1)

    def test_starting_conversation_reuses_existing_conversation(self):
        self.client.force_login(self.requester)

        response = self.client.post(
            reverse('chat:start_conversation', args=[self.item.pk])
        )

        self.assertRedirects(
            response,
            reverse(
                'chat:conversation_detail',
                args=[self.conversation.pk],
            ),
        )
        self.assertEqual(Conversation.objects.count(), 1)

    def test_unread_count_ignores_messages_sent_by_current_user(self):
        message = Message.objects.create(
            conversation=self.conversation,
            sender=self.owner,
            body='New message',
        )

        self.client.force_login(self.requester)

        response = self.client.get(reverse('chat:conversation_list'))

        self.assertEqual(response.status_code, 200)
        conversation = response.context['conversations'][0]
        self.assertEqual(conversation.unread_count, 1)

        self.client.force_login(self.owner)

        response = self.client.get(reverse('chat:conversation_list'))

        self.assertEqual(response.status_code, 200)
        conversation = response.context['conversations'][0]
        self.assertEqual(conversation.unread_count, 0)

    def test_unread_count_handles_other_participant_read_state(self):
        ConversationReadState.objects.create(
            conversation=self.conversation,
            user=self.owner,
        )

        Message.objects.create(
            conversation=self.conversation,
            sender=self.owner,
            body='Message for requester',
        )

        self.client.force_login(self.requester)

        response = self.client.get(reverse('chat:conversation_list'))

        self.assertEqual(response.status_code, 200)
        conversation = response.context['conversations'][0]
        self.assertEqual(conversation.unread_count, 1)
    

    def test_participant_can_fetch_new_messages(self):
        self.client.force_login(self.requester)

        message = Message.objects.create(
            conversation=self.conversation,
            sender=self.owner,
            body='A new message',
        )

        response = self.client.get(
            reverse(
                'chat:conversation_messages',
                args=[self.conversation.pk],
            ),
            {'after_id': 0},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['messages'][0]['id'],
            message.pk,
        )
        self.assertEqual(
            response.json()['messages'][0]['body'],
            'A new message',
        )

    def test_outsider_cannot_fetch_messages(self):
        self.client.force_login(self.outsider)

        response = self.client.get(
            reverse(
                'chat:conversation_messages',
                args=[self.conversation.pk],
            ),
            {'after_id': 0},
        )

        self.assertEqual(response.status_code, 404)

    def test_message_endpoint_rejects_invalid_cursor(self):
        self.client.force_login(self.requester)

        response = self.client.get(
            reverse(
                'chat:conversation_messages',
                args=[self.conversation.pk],
            ),
            {'after_id': 'invalid'},
        )

        self.assertEqual(response.status_code, 400)


class ChatStartRulesTests(TestCase):
    """Who may open a conversation, and when (D4)."""

    def setUp(self):
        from listings.models import Claim

        self.Claim = Claim
        self.owner = User.objects.create_user(username='owner', password='TestPassword123!')
        self.claimant = User.objects.create_user(username='claimant', password='TestPassword123!')
        self.outsider = User.objects.create_user(username='outsider', password='TestPassword123!')
        self.item = Item.objects.create(
            owner=self.owner,
            title='Reserved textbook',
            description='Testing chat rules.',
            category=Item.Category.BOOKS,
            status=Item.Status.RESERVED,
        )

    def start(self, user):
        self.client.force_login(user)
        return self.client.post(reverse('chat:start_conversation', args=[self.item.pk]))

    def test_student_with_an_active_claim_can_chat_about_a_reserved_item(self):
        self.Claim.objects.create(item=self.item, claimant=self.claimant, status=self.Claim.Status.APPROVED)

        response = self.start(self.claimant)

        conversation = Conversation.objects.get(item=self.item, requester=self.claimant)
        self.assertRedirects(response, reverse('chat:conversation_detail', args=[conversation.pk]))
        self.assertEqual(conversation.owner, self.owner)

    def test_outsider_cannot_start_a_chat_on_a_reserved_item(self):
        response = self.start(self.outsider)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Conversation.objects.exists())

    def test_existing_chat_reopens_after_the_item_is_passed_on(self):
        conversation = Conversation.objects.create(item=self.item, owner=self.owner, requester=self.outsider)
        self.item.status = Item.Status.PASSED_ON
        self.item.save(update_fields=['status', 'updated_at'])

        response = self.start(self.outsider)

        self.assertRedirects(response, reverse('chat:conversation_detail', args=[conversation.pk]))

    def test_owner_can_message_a_claimant(self):
        claim = self.Claim.objects.create(item=self.item, claimant=self.claimant)
        self.client.force_login(self.owner)

        response = self.client.post(reverse('chat:start_claimant_conversation', args=[claim.pk]))

        conversation = Conversation.objects.get(item=self.item, requester=self.claimant)
        self.assertEqual(conversation.owner, self.owner)
        self.assertRedirects(response, reverse('chat:conversation_detail', args=[conversation.pk]))

    def test_only_the_item_owner_can_message_its_claimants(self):
        claim = self.Claim.objects.create(item=self.item, claimant=self.claimant)
        self.client.force_login(self.outsider)

        response = self.client.post(reverse('chat:start_claimant_conversation', args=[claim.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Conversation.objects.exists())

    def test_cancelled_claims_cannot_be_messaged(self):
        claim = self.Claim.objects.create(
            item=self.item, claimant=self.claimant, status=self.Claim.Status.CANCELLED,
        )
        self.client.force_login(self.owner)

        response = self.client.post(reverse('chat:start_claimant_conversation', args=[claim.pk]))

        self.assertRedirects(response, reverse('my_posts'))
        self.assertFalse(Conversation.objects.exists())

    def test_messaging_a_claimant_requires_post(self):
        claim = self.Claim.objects.create(item=self.item, claimant=self.claimant)
        self.client.force_login(self.owner)

        response = self.client.get(reverse('chat:start_claimant_conversation', args=[claim.pk]))

        self.assertEqual(response.status_code, 405)


class ChatUnreadCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='unread_user',
            password='TestPassword123!',
        )
        cls.other_user = User.objects.create_user(
            username='unread_other',
            password='TestPassword123!',
        )

        cls.item = Item.objects.create(
            owner=cls.user,
            title='Unread test textbook',
            description='Testing navbar unread counts.',
            category=Item.Category.BOOKS,
        )

        cls.conversation = Conversation.objects.create(
            item=cls.item,
            owner=cls.user,
            requester=cls.other_user,
        )

    def test_anonymous_user_has_zero_unread_messages(self):
        from types import SimpleNamespace

        request = SimpleNamespace(user=AnonymousUser())

        self.assertEqual(chat_unread_count(request), {
            'chat_unread_count': 0,
        })

    def test_unread_count_excludes_own_messages(self):
        from types import SimpleNamespace

        Message.objects.create(
            conversation=self.conversation,
            sender=self.other_user,
            body='A message for the owner.',
        )
        Message.objects.create(
            conversation=self.conversation,
            sender=self.user,
            body='A reply from the owner.',
        )

        request = SimpleNamespace(user=self.user)

        self.assertEqual(
            chat_unread_count(request)['chat_unread_count'],
            1,
        )

    def test_read_state_excludes_older_messages(self):
        from types import SimpleNamespace

        ConversationReadState.objects.create(
            conversation=self.conversation,
            user=self.user,
            last_read_at=timezone.now() - timedelta(minutes=5),
        )

        Message.objects.create(
            conversation=self.conversation,
            sender=self.other_user,
            body='A newer message.',
        )

        request = SimpleNamespace(user=self.user)

        self.assertEqual(
            chat_unread_count(request)['chat_unread_count'],
            1,
        )


@override_settings(
    CHANNEL_LAYERS={
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        },
    },
)
class ChatWebSocketTests(TransactionTestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="ws_owner",
            password="TestPassword123!",
        )
        self.requester = User.objects.create_user(
            username="ws_requester",
            password="TestPassword123!",
        )
        self.outsider = User.objects.create_user(
            username="ws_outsider",
            password="TestPassword123!",
        )
        self.item = Item.objects.create(
            owner=self.owner,
            title="WebSocket test textbook",
            description="Testing real-time chat.",
            category=Item.Category.BOOKS,
        )
        self.conversation = Conversation.objects.create(
            item=self.item,
            owner=self.owner,
            requester=self.requester,
        )

    def make_communicator(self, user):
        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns),
            f"/ws/chat/{self.conversation.pk}/",
        )
        communicator.scope["user"] = user
        return communicator

    def test_anonymous_user_is_rejected(self):
        from django.contrib.auth.models import AnonymousUser

        async def run_test():
            communicator = self.make_communicator(AnonymousUser())
            connected, detail = await communicator.connect()
            self.assertFalse(connected)
            self.assertEqual(detail, 4401)

        async_to_sync(run_test)()

    def test_outsider_is_rejected(self):
        async def run_test():
            communicator = self.make_communicator(self.outsider)
            connected, detail = await communicator.connect()
            self.assertFalse(connected)
            self.assertEqual(detail, 4404)

        async_to_sync(run_test)()

    def test_participant_can_send_and_receive_message(self):
        async def run_test():
            owner_socket = self.make_communicator(self.owner)
            requester_socket = self.make_communicator(self.requester)

            owner_connected, _ = await owner_socket.connect()
            requester_connected, _ = await requester_socket.connect()

            self.assertTrue(owner_connected)
            self.assertTrue(requester_connected)

            await requester_socket.send_json_to({
                "type": "message",
                "body": "  Hello through WebSockets!  ",
                "client_message_id": "test-message-1",
            })

            owner_event = await owner_socket.receive_json_from(
                timeout=2,
            )
            requester_event = await requester_socket.receive_json_from(
                timeout=2,
            )

            self.assertEqual(owner_event["type"], "message")
            self.assertEqual(
                owner_event["message"]["body"],
                "Hello through WebSockets!",
            )
            self.assertEqual(
                requester_event["message"]["id"],
                owner_event["message"]["id"],
            )
            self.assertEqual(
                owner_event["client_message_id"],
                "test-message-1",
            )
            self.assertEqual(
                requester_event["client_message_id"],
                "test-message-1",
            )

            await owner_socket.disconnect()
            await requester_socket.disconnect()

        async_to_sync(run_test)()

        message = Message.objects.get(
            conversation=self.conversation,
        )
        self.assertEqual(message.sender, self.requester)
        self.assertEqual(message.body, "Hello through WebSockets!")

    def test_invalid_messages_are_not_saved(self):
        async def run_test():
            communicator = self.make_communicator(self.requester)
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            for body in ("   ", "x" * 2001, None):
                await communicator.send_json_to({
                    "type": "message",
                    "body": body,
                })
                response = await communicator.receive_json_from(
                    timeout=2,
                )
                self.assertEqual(response["type"], "error")

            await communicator.disconnect()

        async_to_sync(run_test)()

        self.assertFalse(
            Message.objects.filter(
                conversation=self.conversation,
            ).exists()
        )

    
    def test_session_cookie_authenticates_websocket(self):
        self.client.force_login(self.requester)
        session_cookie = self.client.cookies[
            settings.SESSION_COOKIE_NAME
        ].value

        async def run_test():
            application = AuthMiddlewareStack(
                URLRouter(websocket_urlpatterns)
            )
            communicator = WebsocketCommunicator(
                application,
                f"/ws/chat/{self.conversation.pk}/",
                headers=[
                    (
                        b"cookie",
                        (
                            f"{settings.SESSION_COOKIE_NAME}="
                            f"{session_cookie}"
                        ).encode(),
                    ),
                ],
            )

            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            await communicator.disconnect()

        async_to_sync(run_test)()

    
    def test_http_form_message_is_broadcast_to_websocket_clients(self):
        self.client.force_login(self.requester)

        async def run_test():
            communicator = self.make_communicator(self.owner)
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            response = await sync_to_async(
                self.client.post,
                thread_sensitive=True,
            )(
                reverse(
                    "chat:conversation_detail",
                    args=[self.conversation.pk],
                ),
                {"body": "Sent through the existing form"},
            )

            self.assertEqual(response.status_code, 302)

            event = await communicator.receive_json_from(timeout=2)

            self.assertEqual(event["type"], "message")
            self.assertEqual(
                event["message"]["body"],
                "Sent through the existing form",
            )
            self.assertEqual(
                event["message"]["sender_id"],
                self.requester.pk,
            )

            await communicator.disconnect()

        async_to_sync(run_test)()

        message = Message.objects.get(
            conversation=self.conversation,
        )
        self.assertEqual(message.sender, self.requester)