from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import ItemForm
from .models import Item


class ItemModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='student',
            password='test-password-123',
        )

    def test_item_can_be_created(self):
        item = Item.objects.create(
            owner=self.user,
            title='Chemistry textbook',
            description='Used textbook in good condition.',
            category=Item.Category.BOOKS,
        )

        self.assertEqual(item.owner, self.user)
        self.assertEqual(item.title, 'Chemistry textbook')
        self.assertEqual(item.category, Item.Category.BOOKS)

    def test_item_status_defaults_to_available(self):
        item = Item.objects.create(
            owner=self.user,
            title='Calculator',
            description='Working scientific calculator.',
            category=Item.Category.STATIONERY,
        )

        self.assertEqual(item.status, Item.Status.AVAILABLE)

    def test_owner_items_reverse_relationship(self):
        item = Item.objects.create(
            owner=self.user,
            title='School tie',
            description='Clean school tie.',
            category=Item.Category.CLOTHES,
        )

        self.assertEqual(self.user.items.get(), item)

    def test_available_items_are_newest_first(self):
        older_item = Item.objects.create(
            owner=self.user,
            title='Old notebook',
            description='Partly used notebook.',
            category=Item.Category.STATIONERY,
        )
        older_item.created_at = timezone.now() - timedelta(days=1)
        older_item.save(update_fields=['created_at'])

        newer_item = Item.objects.create(
            owner=self.user,
            title='New notebook',
            description='Unused notebook.',
            category=Item.Category.STATIONERY,
        )
        Item.objects.create(
            owner=self.user,
            title='Reserved notebook',
            description='Already reserved.',
            category=Item.Category.STATIONERY,
            status=Item.Status.RESERVED,
        )

        available_items = Item.objects.filter(status=Item.Status.AVAILABLE)

        self.assertEqual(list(available_items), [newer_item, older_item])


class CreateItemViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='student',
            password='test-password-123',
        )
        self.item_data = {
            'title': 'Math textbook',
            'description': 'Used textbook in good condition.',
            'category': Item.Category.BOOKS,
        }

    def test_unauthenticated_get_redirects_to_login(self):
        response = self.client.get(reverse('item_create'))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('item_create')}",
        )

    def test_authenticated_get_has_an_unbound_form(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('item_create'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/item_form.html')
        self.assertIsInstance(response.context['form'], ItemForm)
        self.assertFalse(response.context['form'].is_bound)

    def test_valid_post_creates_item_and_redirects_home(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('item_create'), self.item_data)

        self.assertRedirects(response, reverse('home'))
        item = Item.objects.get()
        self.assertEqual(item.title, self.item_data['title'])
        self.assertEqual(item.owner, self.user)

    def test_missing_fields_show_errors_and_do_not_create_item(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('item_create'), {})

        self.assertEqual(response.status_code, 200)
        self.assertIn('title', response.context['form'].errors)
        self.assertIn('description', response.context['form'].errors)
        self.assertIn('category', response.context['form'].errors)
        self.assertEqual(Item.objects.count(), 0)

    def test_submitted_owner_is_ignored(self):
        other_user = get_user_model().objects.create_user(
            username='other-student',
            password='test-password-123',
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('item_create'),
            {**self.item_data, 'owner': other_user.pk},
        )

        self.assertRedirects(response, reverse('home'))
        self.assertEqual(Item.objects.get().owner, self.user)

    def test_submitted_status_is_ignored_and_defaults_to_available(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('item_create'),
            {**self.item_data, 'status': Item.Status.PASSED_ON},
        )

        self.assertRedirects(response, reverse('home'))
        self.assertEqual(Item.objects.get().status, Item.Status.AVAILABLE)


class HomeViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='student',
            password='test-password-123',
        )

    def test_home_returns_empty_items_and_empty_state_for_anonymous_user(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['items']), [])
        self.assertContains(response, 'No posts yet.')

    def test_home_shows_available_item(self):
        item = Item.objects.create(
            owner=self.user,
            title='Chemistry textbook',
            description='Used textbook in good condition.',
            category=Item.Category.BOOKS,
        )

        response = self.client.get(reverse('home'))

        self.assertIn(item, response.context['items'])
        self.assertContains(response, item.title)

    def test_home_does_not_show_reserved_item(self):
        item = Item.objects.create(
            owner=self.user,
            title='Reserved calculator',
            description='Already reserved.',
            category=Item.Category.STATIONERY,
            status=Item.Status.RESERVED,
        )

        response = self.client.get(reverse('home'))

        self.assertNotIn(item, response.context['items'])
        self.assertNotContains(response, item.title)

    def test_home_does_not_show_passed_on_item(self):
        item = Item.objects.create(
            owner=self.user,
            title='Passed-on tie',
            description='Already collected.',
            category=Item.Category.CLOTHES,
            status=Item.Status.PASSED_ON,
        )

        response = self.client.get(reverse('home'))

        self.assertNotIn(item, response.context['items'])
        self.assertNotContains(response, item.title)

    def test_home_orders_available_items_newest_first(self):
        older_item = Item.objects.create(
            owner=self.user,
            title='Old notebook',
            description='Partly used notebook.',
            category=Item.Category.STATIONERY,
        )
        older_item.created_at = timezone.now() - timedelta(days=1)
        older_item.save(update_fields=['created_at'])

        newer_item = Item.objects.create(
            owner=self.user,
            title='New notebook',
            description='Unused notebook.',
            category=Item.Category.STATIONERY,
        )

        response = self.client.get(reverse('home'))

        self.assertEqual(list(response.context['items']), [newer_item, older_item])

    def test_home_provides_owner_information(self):
        owner = get_user_model().objects.create_user(
            username='item-owner',
            password='test-password-123',
        )
        Item.objects.create(
            owner=owner,
            title='School jacket',
            description='Jacket in good condition.',
            category=Item.Category.CLOTHES,
        )

        response = self.client.get(reverse('home'))

        item = list(response.context['items'])[0]
        self.assertEqual(item.owner.username, 'item-owner')
        self.assertContains(response, 'item-owner')

    def test_home_remains_public_for_logged_out_users(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Login')
        self.assertContains(response, 'Register')

    def test_home_keeps_logged_in_navigation(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Our Vision')
        self.assertContains(response, 'Chat')
        self.assertNotContains(response, 'Login')
        self.assertNotContains(response, 'Register')
