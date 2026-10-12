
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from listings.models import Item
from .context_processors import chat_unread_count
from .models import Conversation, ConversationReadState, Message

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