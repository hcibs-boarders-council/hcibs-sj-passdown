import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from listings.models import Item


User = get_user_model()


class FlashMessageTests(TestCase):
    """Messages are rendered once, on the page the user lands on (base.html)."""

    def setUp(self):
        self.owner = User.objects.create_user(username='owner', password='secure-password-123')
        self.claimant = User.objects.create_user(username='claimant', password='secure-password-123')
        self.item = Item.objects.create(
            owner=self.owner,
            title='Physics notes',
            description='Neat notes.',
            category=Item.Category.BOOKS,
        )

    def test_claim_feedback_is_shown_on_the_redirect_target(self):
        self.client.force_login(self.claimant)

        response = self.client.post(
            reverse('claim_create', kwargs={'pk': self.item.pk}),
            {'note': 'Could I collect this on Friday?'},
            follow=True,
        )

        self.assertContains(response, 'Your claim was sent to the item owner.', count=1)
        self.assertContains(response, 'role="status"')

    def test_messages_are_not_repeated_on_later_pages(self):
        self.client.force_login(self.claimant)
        self.client.post(
            reverse('claim_create', kwargs={'pk': self.item.pk}),
            {'note': 'Hello!'},
        )

        first_page = self.client.get(reverse('my_claims'))
        later_page = self.client.get(reverse('account_detail'))

        self.assertContains(first_page, 'Your claim was sent to the item owner.', count=1)
        self.assertNotContains(later_page, 'Your claim was sent to the item owner.')

    def test_error_messages_are_announced_as_alerts(self):
        self.item.status = Item.Status.RESERVED
        self.item.save(update_fields=['status', 'updated_at'])
        self.client.force_login(self.claimant)

        response = self.client.post(
            reverse('claim_create', kwargs={'pk': self.item.pk}),
            {'note': 'Too late?'},
            follow=True,
        )

        self.assertContains(response, 'This item is no longer available to claim.')
        self.assertContains(response, 'role="alert"')


class AccountDetailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='student',
            password='secure-password-123',
            email='student@example.com',
        )

    def test_account_details_require_login(self):
        response = self.client.get(reverse('account_detail'))

        self.assertRedirects(response, f"{reverse('login')}?next={reverse('account_detail')}")

    def test_successful_update_shows_one_confirmation(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('account_detail'),
            {'first_name': 'Ada', 'last_name': 'Tan', 'email': 'ada@example.com'},
            follow=True,
        )

        self.assertContains(response, 'Your account details were updated.', count=1)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'ada@example.com')

    def test_field_errors_are_linked_to_their_inputs(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('account_detail'),
            {'first_name': 'Ada', 'last_name': 'Tan', 'email': 'not-an-email'},
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('id="id_email_error"', content)
        email_input = re.search(r'<input[^>]*name="email"[^>]*>', content).group(0)
        self.assertIn('aria-invalid="true"', email_input)
        self.assertIn('id_email_error', email_input)


class BaseLayoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='student', password='secure-password-123')

    def test_layout_has_skip_link_and_shared_scripts(self):
        response = self.client.get(reverse('home'))

        self.assertContains(response, 'href="#main-content"')
        self.assertContains(response, 'id="main-content"')
        self.assertContains(response, 'js/ui.js')

    def test_profile_menu_marks_the_current_page(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('my_posts'))

        link = re.search(
            r'<a href="%s" class="profile-dropdown__item"[^>]*>' % re.escape(reverse('my_posts')),
            response.content.decode(),
        ).group(0)
        self.assertIn('aria-current="page"', link)


class RegistrationTests(TestCase):
    """Phase 6: Django's username rules are enforced without server errors."""

    def post(self, **overrides):
        data = {
            'username': 'new_student',
            'email': 'new@example.com',
            'password': 'a-strong-passphrase-42',
            'password_confirmation': 'a-strong-passphrase-42',
        }
        data.update(overrides)
        return self.client.post(reverse('register'), data)

    def test_valid_registration_creates_the_account(self):
        response = self.post()

        self.assertRedirects(response, reverse('login'))
        self.assertTrue(User.objects.filter(username='new_student').exists())

    def test_overlong_username_is_rejected_without_a_server_error(self):
        response = self.post(username='a' * 151)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Usernames can be at most 150 characters.')
        self.assertFalse(User.objects.exists())

    def test_usernames_with_spaces_or_symbols_are_rejected(self):
        for username in ('two words', 'semi;colon', 'emoji🙂'):
            with self.subTest(username=username):
                response = self.post(username=username)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'Usernames can only contain letters, numbers and @ . + - _ (no spaces).')
        self.assertFalse(User.objects.exists())

    def test_usernames_are_unique_regardless_of_case(self):
        User.objects.create_user(username='Alex', password='secure-password-123')

        response = self.post(username='alex')

        self.assertContains(response, 'That username is already taken.')
        self.assertEqual(User.objects.filter(username__iexact='alex').count(), 1)

    def test_a_simultaneous_duplicate_is_reported_not_crashed(self):
        from unittest import mock

        from django.db import IntegrityError

        with mock.patch.object(User.objects, 'create_user', side_effect=IntegrityError):
            response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'That username is already taken.')

    def test_username_rules_are_explained_on_the_form(self):
        response = self.client.get(reverse('register'))

        self.assertContains(response, 'maxlength="150"')
        self.assertContains(response, 'id="id_username_helptext"')
        self.assertContains(response, 'aria-describedby="id_username_helptext"')


class OurVisionAndFooterTests(TestCase):
    def test_our_vision_explains_the_mission_and_guidelines(self):
        response = self.client.get(reverse('our_vision'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="how-it-works"')
        self.assertContains(response, 'id="guidelines"')
        self.assertContains(response, 'Community guidelines')

    def test_footer_has_no_placeholder_links(self):
        response = self.client.get(reverse('home'))

        self.assertNotContains(response, 'is-soon')
        self.assertContains(response, f'href="{reverse("our_vision")}#guidelines"')
        self.assertNotContains(response, f'href="{reverse("chat:conversation_list")}"')

    def test_footer_links_to_chats_when_logged_in(self):
        self.client.force_login(User.objects.create_user(username='student', password='secure-password-123'))

        response = self.client.get(reverse('home'))

        self.assertContains(response, f'href="{reverse("chat:conversation_list")}">Chats</a>')


class AccountEmptyStateTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user(username='newcomer', password='secure-password-123'))

    def test_my_posts_empty_state_offers_posting(self):
        response = self.client.get(reverse('my_posts'))

        self.assertContains(response, "You haven't posted anything yet")
        self.assertContains(response, f'href="{reverse("item_create")}"')

    def test_my_claims_empty_state_offers_browsing(self):
        response = self.client.get(reverse('my_claims'))

        self.assertContains(response, 'No claims yet')
        self.assertContains(response, 'Browse passdowns')
