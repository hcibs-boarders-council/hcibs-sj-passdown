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
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace

from django.db import connection
from django.test.utils import CaptureQueriesContext

from listings.models import Item
from . import services
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



# ---------------------------------------------------------------------------
# Live chat: services, read state, idempotency, notifications (Phase 4)
# ---------------------------------------------------------------------------

class ChatFixtureMixin:
    def make_people(self):
        self.owner = User.objects.create_user(username='rt_owner', password='TestPassword123!')
        self.requester = User.objects.create_user(username='rt_requester', password='TestPassword123!')
        self.outsider = User.objects.create_user(username='rt_outsider', password='TestPassword123!')
        self.item = Item.objects.create(
            owner=self.owner,
            title='Realtime test book',
            description='Testing live chat.',
            category=Item.Category.BOOKS,
        )
        self.conversation = Conversation.objects.create(
            item=self.item,
            owner=self.owner,
            requester=self.requester,
        )


class ReadStateTests(ChatFixtureMixin, TestCase):
    def setUp(self):
        self.make_people()

    def test_marking_read_up_to_a_message_keeps_later_ones_unread(self):
        first = Message.objects.create(conversation=self.conversation, sender=self.requester, body='One')
        second = Message.objects.create(conversation=self.conversation, sender=self.requester, body='Two')
        Message.objects.filter(pk=second.pk).update(created_at=first.created_at + timedelta(seconds=5))

        self.conversation.mark_read(self.owner, up_to=first)

        self.assertEqual(services.unread_counts(self.owner, self.conversation.pk)['conversation'], 1)

    def test_read_position_never_moves_backwards(self):
        first = Message.objects.create(conversation=self.conversation, sender=self.requester, body='One')
        second = Message.objects.create(conversation=self.conversation, sender=self.requester, body='Two')
        Message.objects.filter(pk=second.pk).update(created_at=first.created_at + timedelta(seconds=5))
        second.refresh_from_db()

        self.conversation.mark_read(self.owner, up_to=second)
        self.conversation.mark_read(self.owner, up_to=first)

        self.assertEqual(services.unread_total(self.owner), 0)

    def test_cannot_mark_read_with_a_message_from_another_conversation(self):
        other = Conversation.objects.create(item=self.item, owner=self.owner, requester=self.outsider)
        foreign = Message.objects.create(conversation=other, sender=self.outsider, body='Hi')

        with self.assertRaises(Exception):
            self.conversation.mark_read(self.owner, up_to=foreign)

    def test_mark_read_endpoint_accepts_a_cursor(self):
        first = Message.objects.create(conversation=self.conversation, sender=self.requester, body='One')
        second = Message.objects.create(conversation=self.conversation, sender=self.requester, body='Two')
        Message.objects.filter(pk=second.pk).update(created_at=first.created_at + timedelta(seconds=5))
        self.client.force_login(self.owner)
        url = reverse('chat:conversation_mark_read', args=[self.conversation.pk])

        response = self.client.post(url, {'last_message_id': first.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['conversation_unread'], 1)
        self.assertEqual(response.json()['unread_total'], 1)

    def test_mark_read_endpoint_rejects_bad_cursors(self):
        other = Conversation.objects.create(item=self.item, owner=self.owner, requester=self.outsider)
        foreign = Message.objects.create(conversation=other, sender=self.outsider, body='Hi')
        self.client.force_login(self.owner)
        url = reverse('chat:conversation_mark_read', args=[self.conversation.pk])

        self.assertEqual(self.client.post(url, {'last_message_id': 'abc'}).status_code, 400)
        self.assertEqual(self.client.post(url, {'last_message_id': foreign.pk}).status_code, 400)

    def test_mark_read_endpoint_is_participants_only(self):
        self.client.force_login(self.outsider)

        response = self.client.post(reverse('chat:conversation_mark_read', args=[self.conversation.pk]))

        self.assertEqual(response.status_code, 404)

    def test_opening_a_conversation_marks_its_messages_read(self):
        Message.objects.create(conversation=self.conversation, sender=self.requester, body='Hello')
        self.client.force_login(self.owner)

        response = self.client.get(reverse('chat:conversation_detail', args=[self.conversation.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['latest_message_id'], self.conversation.messages.get().pk)
        self.assertContains(response, 'data-latest-message-id="%s"' % self.conversation.messages.get().pk)
        self.assertEqual(services.unread_total(self.owner), 0)

    def test_unread_summary_endpoint(self):
        Message.objects.create(conversation=self.conversation, sender=self.requester, body='Hello')

        self.assertEqual(self.client.get(reverse('chat:unread_summary')).status_code, 401)

        self.client.force_login(self.owner)
        response = self.client.get(reverse('chat:unread_summary'))
        self.assertEqual(response.json(), {'unread_total': 1})
        self.assertIn('no-cache', response.get('Cache-Control', ''))


class MessageIdempotencyTests(ChatFixtureMixin, TestCase):
    def setUp(self):
        self.make_people()

    def test_same_client_id_returns_the_stored_message(self):
        first, created = services.create_message(
            conversation=self.conversation, sender=self.requester, body='Hi', client_message_id='abc-123',
        )
        again, created_again = services.create_message(
            conversation=self.conversation, sender=self.requester, body='Hi', client_message_id='abc-123',
        )

        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(Message.objects.count(), 1)

    def test_client_id_cannot_be_reused_across_conversations(self):
        other = Conversation.objects.create(item=self.item, owner=self.owner, requester=self.outsider)
        services.create_message(
            conversation=self.conversation, sender=self.owner, body='Hi', client_message_id='same-id',
        )

        with self.assertRaises(services.ClientMessageIdConflict):
            services.create_message(conversation=other, sender=self.owner, body='Hi', client_message_id='same-id')

    def test_form_fallback_with_a_client_id_is_not_duplicated(self):
        self.client.force_login(self.requester)
        url = reverse('chat:conversation_detail', args=[self.conversation.pk])

        for _ in range(2):
            self.client.post(url, {'body': 'Hello there', 'client_message_id': 'form-retry-1'})

        self.assertEqual(Message.objects.filter(body='Hello there').count(), 1)

    def test_json_fallback_returns_the_stored_message_once(self):
        self.client.force_login(self.requester)
        url = reverse('chat:conversation_detail', args=[self.conversation.pk])
        payload = {'body': '  Still free?  ', 'client_message_id': 'http-send-1'}

        first = self.client.post(url, payload, HTTP_ACCEPT='application/json')
        again = self.client.post(url, payload, HTTP_ACCEPT='application/json')

        self.assertEqual(first.status_code, 201)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(first.json()['client_message_id'], 'http-send-1')
        self.assertEqual(first.json()['message']['body'], 'Still free?')
        self.assertEqual(first.json()['message']['id'], again.json()['message']['id'])
        self.assertEqual(Message.objects.filter(body='Still free?').count(), 1)

    def test_json_fallback_reports_validation_errors(self):
        self.client.force_login(self.requester)
        url = reverse('chat:conversation_detail', args=[self.conversation.pk])

        response = self.client.post(url, {'body': '   '}, HTTP_ACCEPT='application/json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
        self.assertFalse(Message.objects.exists())

    def test_json_fallback_is_participants_only(self):
        self.client.force_login(self.outsider)
        url = reverse('chat:conversation_detail', args=[self.conversation.pk])

        response = self.client.post(url, {'body': 'Let me in'}, HTTP_ACCEPT='application/json')

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Message.objects.exists())

    def test_sending_marks_the_conversation_read_for_the_sender(self):
        Message.objects.create(conversation=self.conversation, sender=self.owner, body='Ping')

        services.create_message(conversation=self.conversation, sender=self.requester, body='Pong')

        self.assertEqual(services.unread_total(self.requester), 0)
        self.assertEqual(services.unread_total(self.owner), 1)

    def test_display_time_uses_singapore_time(self):
        message = Message.objects.create(conversation=self.conversation, sender=self.owner, body='Hi')
        utc_time = datetime(2026, 10, 13, 0, 30, tzinfo=dt_timezone.utc)
        Message.objects.filter(pk=message.pk).update(created_at=utc_time)
        message.refresh_from_db()

        self.assertIn('8:30', services.serialize_message(message)['display_time'])


class ConversationListTests(ChatFixtureMixin, TestCase):
    def setUp(self):
        self.make_people()

    def test_list_shows_latest_message_preview_and_unread_count(self):
        Message.objects.create(conversation=self.conversation, sender=self.requester, body='Older')
        latest = Message.objects.create(conversation=self.conversation, sender=self.requester, body='Newest note')
        Message.objects.filter(pk=latest.pk).update(created_at=timezone.now() + timedelta(seconds=5))
        self.client.force_login(self.owner)

        response = self.client.get(reverse('chat:conversation_list'))

        conversation = list(response.context['conversations'])[0]
        self.assertEqual(conversation.latest_body, 'Newest note')
        self.assertEqual(conversation.unread_count, 2)
        self.assertContains(response, 'data-conversation-id="%s"' % self.conversation.pk)
        self.assertContains(response, 'Newest note')

    def test_list_marks_own_latest_message(self):
        Message.objects.create(conversation=self.conversation, sender=self.owner, body='My reply')
        self.client.force_login(self.owner)

        response = self.client.get(reverse('chat:conversation_list'))

        self.assertContains(response, 'You: My reply')

    def test_list_query_count_does_not_grow_with_messages_or_chats(self):
        self.client.force_login(self.owner)
        Message.objects.create(conversation=self.conversation, sender=self.requester, body='Hi')

        with CaptureQueriesContext(connection) as small:
            self.client.get(reverse('chat:conversation_list'))

        for number in range(3):
            student = User.objects.create_user(username=f'student{number}', password='TestPassword123!')
            conversation = Conversation.objects.create(item=self.item, owner=self.owner, requester=student)
            for index in range(5):
                Message.objects.create(conversation=conversation, sender=student, body=f'Message {index}')

        with CaptureQueriesContext(connection) as large:
            self.client.get(reverse('chat:conversation_list'))

        self.assertEqual(len(small.captured_queries), len(large.captured_queries))

    def test_outsiders_never_see_other_conversations(self):
        Message.objects.create(conversation=self.conversation, sender=self.requester, body='Private note')
        self.client.force_login(self.outsider)

        response = self.client.get(reverse('chat:conversation_list'))

        self.assertNotContains(response, 'Private note')
        self.assertEqual(list(response.context['conversations']), [])


@override_settings(
    CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}},
)
class RealtimeTests(ChatFixtureMixin, TransactionTestCase):
    def setUp(self):
        self.make_people()

    def communicator(self, user, path=None, session_key=None):
        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns),
            path or f'/ws/chat/{self.conversation.pk}/',
        )
        communicator.scope['user'] = user
        if session_key is not None:
            communicator.scope['session'] = SimpleNamespace(session_key=session_key)
        return communicator

    def notifications(self, user, session_key=None):
        return self.communicator(user, '/ws/notifications/', session_key)

    def test_notification_socket_requires_login(self):
        async def run():
            socket = self.notifications(AnonymousUser())
            connected, code = await socket.connect()
            self.assertFalse(connected)
            self.assertEqual(code, 4401)

        async_to_sync(run)()

    def test_notification_socket_starts_with_the_unread_total(self):
        Message.objects.create(conversation=self.conversation, sender=self.requester, body='Hi')

        async def run():
            socket = self.notifications(self.owner)
            connected, _ = await socket.connect()
            self.assertTrue(connected)
            hello = await socket.receive_json_from(timeout=2)
            self.assertEqual(hello, {'type': 'hello', 'unread_total': 1})
            await socket.disconnect()

        async_to_sync(run)()

    def test_recipient_is_notified_with_server_counted_unread_totals(self):
        async def run():
            owner_alerts = self.notifications(self.owner)
            requester_alerts = self.notifications(self.requester)
            outsider_alerts = self.notifications(self.outsider)
            for socket in (owner_alerts, requester_alerts, outsider_alerts):
                connected, _ = await socket.connect()
                self.assertTrue(connected)
                await socket.receive_json_from(timeout=2)  # hello

            chat = self.communicator(self.requester)
            await chat.connect()
            await chat.send_json_to({'type': 'message', 'body': 'Is it free?', 'client_message_id': 'n-1'})
            echo = await chat.receive_json_from(timeout=2)
            self.assertEqual(echo['type'], 'message')

            alert = await owner_alerts.receive_json_from(timeout=2)
            self.assertEqual(alert['type'], 'message')
            self.assertEqual(alert['conversation_id'], self.conversation.pk)
            self.assertEqual(alert['unread_total'], 1)
            self.assertEqual(alert['conversation_unread'], 1)
            self.assertEqual(alert['counterpart_name'], 'rt_requester')
            self.assertEqual(alert['message']['body'], 'Is it free?')

            own_copy = await requester_alerts.receive_json_from(timeout=2)
            self.assertEqual(own_copy['unread_total'], 0)
            self.assertEqual(own_copy['counterpart_name'], 'rt_owner')

            # Nothing about this conversation reaches anyone else.
            self.assertTrue(await outsider_alerts.receive_nothing(timeout=0.3))

            for socket in (owner_alerts, requester_alerts, outsider_alerts, chat):
                await socket.disconnect()

        async_to_sync(run)()

    def test_resending_the_same_client_id_does_not_duplicate(self):
        async def run():
            sender = self.communicator(self.requester)
            receiver = self.communicator(self.owner)
            await sender.connect()
            await receiver.connect()

            payload = {'type': 'message', 'body': 'Only once', 'client_message_id': 'retry-me'}
            await sender.send_json_to(payload)
            first = await sender.receive_json_from(timeout=2)
            await receiver.receive_json_from(timeout=2)

            await sender.send_json_to(payload)
            second = await sender.receive_json_from(timeout=2)
            self.assertEqual(first['message']['id'], second['message']['id'])
            self.assertEqual(second['client_message_id'], 'retry-me')
            # The other participant isn't sent the duplicate.
            self.assertTrue(await receiver.receive_nothing(timeout=0.3))

            await sender.disconnect()
            await receiver.disconnect()

        async_to_sync(run)()
        self.assertEqual(Message.objects.filter(body='Only once').count(), 1)

    def test_malformed_client_ids_are_rejected(self):
        async def run():
            socket = self.communicator(self.requester)
            await socket.connect()
            await socket.send_json_to({'type': 'message', 'body': 'Hi', 'client_message_id': 'has spaces!'})
            response = await socket.receive_json_from(timeout=2)
            self.assertEqual(response['type'], 'error')
            await socket.disconnect()

        async_to_sync(run)()
        self.assertFalse(Message.objects.exists())

    def test_heartbeat_ping_gets_a_pong(self):
        async def run():
            for socket in (self.communicator(self.requester), self.notifications(self.requester)):
                await socket.connect()
                if socket.scope['path'].endswith('/notifications/'):
                    await socket.receive_json_from(timeout=2)  # hello
                await socket.send_json_to({'type': 'ping'})
                self.assertEqual(await socket.receive_json_from(timeout=2), {'type': 'pong'})
                await socket.disconnect()

        async_to_sync(run)()

    def test_sending_too_fast_is_rate_limited(self):
        async def run():
            socket = self.communicator(self.requester)
            await socket.connect()
            errors = 0
            for number in range(12):
                await socket.send_json_to({
                    'type': 'message', 'body': f'Spam {number}', 'client_message_id': f'spam-{number}',
                })
                reply = await socket.receive_json_from(timeout=2)
                if reply['type'] == 'error':
                    errors += 1
            self.assertEqual(errors, 2)
            await socket.disconnect()

        async_to_sync(run)()
        self.assertEqual(Message.objects.count(), 10)

    def test_reading_in_one_tab_updates_the_others(self):
        Message.objects.create(conversation=self.conversation, sender=self.requester, body='Hi')
        self.client.force_login(self.owner)

        async def run():
            other_tab = self.notifications(self.owner)
            await other_tab.connect()
            hello = await other_tab.receive_json_from(timeout=2)
            self.assertEqual(hello['unread_total'], 1)

            await sync_to_async(self.client.post, thread_sensitive=True)(
                reverse('chat:conversation_mark_read', args=[self.conversation.pk]),
            )

            update = await other_tab.receive_json_from(timeout=2)
            self.assertEqual(update['type'], 'read')
            self.assertEqual(update['unread_total'], 0)
            await other_tab.disconnect()

        async_to_sync(run)()

    def test_logout_closes_only_that_sessions_sockets(self):
        self.client.force_login(self.owner)
        session_key = self.client.session.session_key

        async def run():
            this_device = self.notifications(self.owner, session_key=session_key)
            other_device = self.notifications(self.owner, session_key='another-device')
            for socket in (this_device, other_device):
                await socket.connect()
                await socket.receive_json_from(timeout=2)

            await sync_to_async(self.client.post, thread_sensitive=True)(reverse('logout'))

            closed = await this_device.receive_output(timeout=2)
            self.assertEqual(closed['type'], 'websocket.close')
            self.assertEqual(closed['code'], 4401)
            self.assertTrue(await other_device.receive_nothing(timeout=0.3))
            await other_device.disconnect()

        async_to_sync(run)()


class ReviewHardeningTests(ChatFixtureMixin, TransactionTestCase):
    """Fixes from the code review: deactivated accounts, logout from anywhere,
    and a conversation deleted while a message is being sent."""

    def setUp(self):
        self.make_people()

    @override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
    def test_deactivated_account_cannot_keep_sending_on_an_open_socket(self):
        async def run():
            socket = WebsocketCommunicator(URLRouter(websocket_urlpatterns), f'/ws/chat/{self.conversation.pk}/')
            socket.scope['user'] = self.requester
            connected, _ = await socket.connect()
            self.assertTrue(connected)

            await sync_to_async(User.objects.filter(pk=self.requester.pk).update)(is_active=False)
            await socket.send_json_to({'type': 'message', 'body': 'Still here?', 'client_message_id': 'after-ban'})

            closed = await socket.receive_output(timeout=2)
            self.assertEqual(closed['type'], 'websocket.close')
            self.assertEqual(closed['code'], 4401)

        async_to_sync(run)()
        self.assertFalse(Message.objects.exists())

    def test_any_logout_closes_that_sessions_sockets(self):
        from unittest import mock

        self.client.force_login(self.owner)
        session_key = self.client.session.session_key

        with mock.patch('chat.signals.end_session_sockets') as end_sockets:
            self.client.logout()  # the same signal fires for the admin's logout

        end_sockets.assert_called_once_with(self.owner.pk, session_key)

    def test_message_to_a_deleted_conversation_is_a_404_not_a_crash(self):
        from unittest import mock

        from django.db import IntegrityError

        self.client.force_login(self.requester)
        url = reverse('chat:conversation_detail', args=[self.conversation.pk])

        with mock.patch('chat.services.Message.objects.create', side_effect=IntegrityError):
            response = self.client.post(url, {'body': 'Hello?'}, HTTP_ACCEPT='application/json')

        self.assertEqual(response.status_code, 404)

    def test_integrity_errors_other_than_retries_are_not_swallowed(self):
        from unittest import mock

        from django.db import IntegrityError

        with mock.patch('chat.services.Message.objects.create', side_effect=IntegrityError):
            with self.assertRaises(IntegrityError):
                services.create_message(
                    conversation=self.conversation, sender=self.requester, body='Hi', client_message_id='never-stored',
                )
