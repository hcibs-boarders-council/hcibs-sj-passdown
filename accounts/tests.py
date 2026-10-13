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
