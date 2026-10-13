import threading
from io import BytesIO
from os import urandom
from tempfile import TemporaryDirectory
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from PIL import Image

from chat.models import Conversation

from .forms import MAX_PHOTO_COUNT, MAX_PHOTO_SIZE, ItemForm
from .models import Claim, Item, ItemPhoto

from datetime import timedelta

from django.utils import timezone

class ListingPhotoTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_directory = TemporaryDirectory()
        cls.media_override = override_settings(MEDIA_ROOT=cls.media_directory.name)
        cls.media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls.media_override.disable()
        cls.media_directory.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='poster',
            password='secure-password-123',
        )
        self.other_user = get_user_model().objects.create_user(
            username='other-poster',
            password='secure-password-123',
        )

    def image_file(self, name='photo.png', image_format='PNG'):
        image_data = BytesIO()
        Image.new('RGB', (40, 30), color='coral').save(image_data, format=image_format)
        content_type = {
            'JPEG': 'image/jpeg',
            'PNG': 'image/png',
            'WEBP': 'image/webp',
            'GIF': 'image/gif',
        }[image_format]
        return SimpleUploadedFile(name, image_data.getvalue(), content_type=content_type)

    def oversized_image_file(self):
        image_data = BytesIO()
        image = Image.frombytes('RGB', (1800, 1200), urandom(1800 * 1200 * 3))
        image.save(image_data, format='PNG')
        return SimpleUploadedFile('large-photo.png', image_data.getvalue(), content_type='image/png')

    def post_data(self, photos):
        return {
            'title': 'Math revision guide',
            'description': 'Useful notes for the next owner.',
            'category': Item.Category.BOOKS,
            'photos': photos,
        }

    def create_item_with_photos(self, owner=None, photo_count=1):
        item = Item.objects.create(
            owner=owner or self.user,
            title='Chemistry notes',
            description='A complete set of notes.',
            category=Item.Category.BOOKS,
        )
        photos = []
        for position in range(photo_count):
            photo = ItemPhoto.objects.create(
                item=item,
                image=self.image_file(f'photo-{position}.png'),
                position=position,
            )
            photos.append(photo)
        return item, photos

    def test_create_item_with_one_photo(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('item_create'),
            self.post_data([self.image_file()]),
        )

        item = Item.objects.get(title='Math revision guide')
        # Posting now lands on the new listing (with a confirmation message).
        self.assertRedirects(response, reverse('item_detail', kwargs={'pk': item.pk}))
        self.assertEqual(item.owner, self.user)
        self.assertEqual(item.status, Item.Status.AVAILABLE)
        self.assertEqual(item.photos.count(), 1)
        self.assertEqual(item.photos.get().position, 0)

    def test_create_item_accepts_five_photos_in_upload_order(self):
        self.client.force_login(self.user)
        photos = [self.image_file(f'photo-{number}.png') for number in range(5)]

        response = self.client.post(reverse('item_create'), self.post_data(photos))

        item = Item.objects.get(title='Math revision guide')
        self.assertRedirects(response, reverse('item_detail', kwargs={'pk': item.pk}))
        saved_photos = list(item.photos.all())
        self.assertEqual(len(saved_photos), MAX_PHOTO_COUNT)
        self.assertEqual([photo.position for photo in saved_photos], [0, 1, 2, 3, 4])

    def test_create_item_rejects_more_than_five_photos(self):
        self.client.force_login(self.user)
        photos = [self.image_file(f'photo-{number}.png') for number in range(6)]

        response = self.client.post(reverse('item_create'), self.post_data(photos))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Item.objects.count(), 0)
        self.assertIn('You can upload up to 5 photos.', response.context['form'].errors['photos'])

    def test_create_item_requires_a_photo(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('item_create'), self.post_data([]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Item.objects.count(), 0)
        self.assertIn('Add at least one photo.', response.context['form'].errors['photos'])

    def test_create_item_rejects_invalid_or_unsupported_images(self):
        self.client.force_login(self.user)

        invalid = SimpleUploadedFile('notes.txt', b'not an image', content_type='text/plain')
        response = self.client.post(reverse('item_create'), self.post_data([invalid]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Item.objects.count(), 0)
        self.assertIn('Upload a valid JPEG, PNG, or WebP image.', response.context['form'].errors['photos'])

        response = self.client.post(
            reverse('item_create'),
            self.post_data([self.image_file('animated.gif', 'GIF')]),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Item.objects.count(), 0)
        self.assertIn('Upload only JPEG, PNG, or WebP photos.', response.context['form'].errors['photos'])

    def test_create_item_rejects_an_oversized_photo(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('item_create'),
            self.post_data([self.oversized_image_file()]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Item.objects.count(), 0)
        self.assertIn('Each photo must be 5 MB or smaller.', response.context['form'].errors['photos'])

    def test_create_item_ignores_submitted_owner_status_and_item(self):
        self.client.force_login(self.user)
        other_item, _ = self.create_item_with_photos(owner=self.other_user)
        data = self.post_data([self.image_file()])
        data.update(
            {
                'owner': self.other_user.pk,
                'status': Item.Status.PASSED_ON,
                'item': other_item.pk,
            },
        )

        response = self.client.post(reverse('item_create'), data)

        new_item = Item.objects.get(title='Math revision guide')
        self.assertRedirects(response, reverse('item_detail', kwargs={'pk': new_item.pk}))
        self.assertEqual(new_item.owner, self.user)
        self.assertEqual(new_item.status, Item.Status.AVAILABLE)
        self.assertNotEqual(new_item.pk, other_item.pk)
        self.assertEqual(new_item.photos.count(), 1)

    def test_home_shows_only_the_primary_photo(self):
        item, photos = self.create_item_with_photos(photo_count=2)

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, photos[0].image.url)
        self.assertNotContains(response, photos[1].image.url)
        self.assertContains(response, reverse('item_detail', kwargs={'pk': item.pk}))

    def test_logged_out_user_is_redirected_from_item_detail(self):
        item, _ = self.create_item_with_photos()
        detail_url = reverse('item_detail', kwargs={'pk': item.pk})

        response = self.client.get(detail_url)

        self.assertRedirects(response, f'{reverse("login")}?next={detail_url}')

    def test_login_returns_user_to_the_requested_item_detail(self):
        item, _ = self.create_item_with_photos()
        detail_url = reverse('item_detail', kwargs={'pk': item.pk})

        response = self.client.post(
            reverse('login'),
            {
                'username': self.other_user.username,
                'password': 'secure-password-123',
                'next': detail_url,
            },
        )

        self.assertRedirects(response, detail_url)

    def test_logged_in_user_can_navigate_item_photos(self):
        item, photos = self.create_item_with_photos(photo_count=3)
        self.client.force_login(self.other_user)

        response = self.client.get(reverse('item_detail', kwargs={'pk': item.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_photo'], photos[0])
        self.assertContains(response, photos[0].image.url)
        self.assertContains(response, photos[1].image.url)

        response = self.client.get(
            reverse('item_detail', kwargs={'pk': item.pk}),
            {'photo': photos[1].pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_photo'], photos[1])
        self.assertEqual(response.context['previous_photo'], photos[0])
        self.assertEqual(response.context['next_photo'], photos[2])


class HomeViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='student',
            password='test-password-123',
        )

    def test_home_shows_available_item(self):
        item = Item.objects.create(
            owner=self.user,
            title='Chemistry textbook',
            description='Used textbook in good condition.',
            category=Item.Category.BOOKS,
        )

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, item.title)


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

        self.assertEqual(
            list(response.context['items']),
            [newer_item, older_item],
        )

    def test_home_provides_owner_information(self):
        Item.objects.create(
            owner=self.user,
            title='School jacket',
            description='Jacket in good condition.',
            category=Item.Category.CLOTHES,
        )

        response = self.client.get(reverse('home'))

        item = list(response.context['items'])[0]
        self.assertEqual(item.owner.username, 'student')
        self.assertContains(response, 'student')

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


class CreateItemViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
        username='student',
        password='test-password-123',
        )

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
        self.assertTemplateUsed(response, 'listings/item_form.html')
        self.assertIsInstance(response.context['form'], ItemForm)
        self.assertFalse(response.context['form'].is_bound)

    def test_missing_fields_show_errors_without_creating_item(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('item_create'), {})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'listings/item_form.html')

        form = response.context['form']
        self.assertFalse(form.is_valid())

        for field in ('title', 'description', 'category', 'photos'):
            with self.subTest(field=field):
                self.assertIn(field, form.errors)

        self.assertEqual(Item.objects.count(), 0)

class ClaimWorkflowTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username='item-owner',
            password='secure-password-123',
        )
        self.claimant = get_user_model().objects.create_user(
            username='item-claimant',
            password='secure-password-123',
        )
        self.other_claimant = get_user_model().objects.create_user(
            username='other-claimant',
            password='secure-password-123',
        )
        self.item = Item.objects.create(
            owner=self.owner,
            title='Chemistry notes',
            description='JC chemistry notes',
            category=Item.Category.BOOKS,
            status=Item.Status.AVAILABLE,
        )

    def create_claim(self, claimant=None, status=Claim.Status.PENDING):
        return Claim.objects.create(
            item=self.item,
            claimant=claimant or self.claimant,
            status=status,
            note='I would like this item.',
        )

    def test_claimant_can_submit_claim(self):
        self.client.force_login(self.claimant)

        response = self.client.post(
            reverse('claim_create', kwargs={'pk': self.item.pk}),
            {'note': 'I would like these notes.'},
        )

        self.assertRedirects(response, reverse('my_claims'))
        claim = Claim.objects.get(item=self.item, claimant=self.claimant)
        self.assertEqual(claim.status, Claim.Status.PENDING)
        self.assertEqual(claim.note, 'I would like these notes.')

    def test_user_cannot_claim_own_item(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('claim_create', kwargs={'pk': self.item.pk}),
            {'note': 'I want my own item.'},
        )

        self.assertEqual(
            response.url,
            reverse('item_detail', kwargs={'pk': self.item.pk}),
        )
        self.assertFalse(Claim.objects.filter(item=self.item).exists())

    def test_duplicate_claim_is_prevented(self):
        self.create_claim()
        self.client.force_login(self.claimant)

        response = self.client.post(
            reverse('claim_create', kwargs={'pk': self.item.pk}),
            {'note': 'Another request.'},
        )

        self.assertRedirects(response, reverse('my_claims'))
        self.assertEqual(
            Claim.objects.filter(item=self.item, claimant=self.claimant).count(),
            1,
        )

    def test_owner_can_approve_claim_and_decline_other_pending_claims(self):
        selected_claim = self.create_claim()
        other_claim = self.create_claim(claimant=self.other_claimant)
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                'claim_update',
                kwargs={'pk': selected_claim.pk, 'action': 'approve'},
            ),
        )

        self.assertRedirects(response, reverse('my_posts'))

        selected_claim.refresh_from_db()
        other_claim.refresh_from_db()
        self.item.refresh_from_db()

        self.assertEqual(selected_claim.status, Claim.Status.APPROVED)
        self.assertIsNotNone(selected_claim.decided_at)
        self.assertEqual(other_claim.status, Claim.Status.DECLINED)
        self.assertIsNotNone(other_claim.decided_at)
        self.assertEqual(self.item.status, Item.Status.RESERVED)

    def test_non_owner_cannot_approve_claim(self):
        claim = self.create_claim()
        self.client.force_login(self.other_claimant)

        response = self.client.post(
            reverse(
                'claim_update',
                kwargs={'pk': claim.pk, 'action': 'approve'},
            ),
        )

        self.assertRedirects(response, reverse('my_posts'))
        claim.refresh_from_db()
        self.item.refresh_from_db()

        self.assertEqual(claim.status, Claim.Status.PENDING)
        self.assertEqual(self.item.status, Item.Status.AVAILABLE)

    def test_claimant_can_cancel_pending_claim(self):
        claim = self.create_claim()
        self.client.force_login(self.claimant)

        response = self.client.post(
            reverse(
                'claim_update',
                kwargs={'pk': claim.pk, 'action': 'cancel'},
            ),
        )

        self.assertRedirects(response, reverse('my_claims'))
        claim.refresh_from_db()
        self.assertEqual(claim.status, Claim.Status.CANCELLED)
        self.assertIsNotNone(claim.decided_at)

    def test_owner_can_complete_approved_claim(self):
        claim = self.create_claim(status=Claim.Status.APPROVED)
        self.item.status = Item.Status.RESERVED
        self.item.save(update_fields=['status', 'updated_at'])
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                'claim_update',
                kwargs={'pk': claim.pk, 'action': 'complete'},
            ),
        )

        self.assertRedirects(response, reverse('my_posts'))
        claim.refresh_from_db()
        self.item.refresh_from_db()

        self.assertEqual(claim.status, Claim.Status.COMPLETED)
        self.assertEqual(self.item.status, Item.Status.PASSED_ON)


class HomeSearchFilterTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='senior',
            password='secure-password-123',
        )
        self.chem_book = self.make_item('Chemistry textbook', 'Lightly used', Item.Category.BOOKS)
        self.math_book = self.make_item('Maths ten-year series', 'Some pencil marks', Item.Category.BOOKS)
        self.calculator = self.make_item('Graphing calculator', 'Works with chemistry apps', Item.Category.STATIONERY)
        self.jacket = self.make_item('School jacket', 'Size M', Item.Category.CLOTHES)

    def make_item(self, title, description, category, status=Item.Status.AVAILABLE):
        return Item.objects.create(
            owner=self.user,
            title=title,
            description=description,
            category=category,
            status=status,
        )

    def get_home(self, **params):
        return self.client.get(reverse('home'), params)

    def test_filters_by_multiple_categories(self):
        response = self.get_home(category=['books', 'clothes'])

        self.assertCountEqual(
            response.context['items'],
            [self.chem_book, self.math_book, self.jacket],
        )
        self.assertEqual(response.context['selected_categories'], ['books', 'clothes'])
        self.assertEqual(response.context['filter_label'], 'Books +1')

    def test_unknown_and_duplicate_categories_are_ignored(self):
        response = self.get_home(category=['books', 'books', 'bogus', ''])

        self.assertEqual(response.context['selected_categories'], ['books'])
        self.assertEqual(response.context['category'], 'books')
        self.assertCountEqual(response.context['items'], [self.chem_book, self.math_book])

    def test_invalid_only_categories_show_everything(self):
        response = self.get_home(category='not-a-category')

        self.assertEqual(response.context['selected_categories'], [])
        self.assertEqual(response.context['result_count'], 4)

    def test_search_matches_title_and_description_case_insensitively(self):
        response = self.get_home(q='CHEMISTRY')

        self.assertCountEqual(response.context['items'], [self.chem_book, self.calculator])

    def test_search_and_categories_combine(self):
        response = self.get_home(q='chemistry', category='stationery')

        self.assertEqual(list(response.context['items']), [self.calculator])
        self.assertContains(response, '1 item matching')

    def test_search_never_returns_unavailable_items(self):
        reserved = self.make_item('Chemistry notes', 'Reserved copy', Item.Category.BOOKS, Item.Status.RESERVED)
        passed_on = self.make_item('Chemistry flashcards', 'Gone', Item.Category.BOOKS, Item.Status.PASSED_ON)

        response = self.get_home(q='chemistry', category='books')

        self.assertNotIn(reserved, response.context['items'])
        self.assertNotIn(passed_on, response.context['items'])
        self.assertEqual(list(response.context['items']), [self.chem_book])

    def test_filter_checkboxes_reflect_the_selection(self):
        response = self.get_home(category='books')
        content = response.content.decode()

        self.assertRegex(content, r'<input type="checkbox" name="category" value="books" checked>')
        self.assertRegex(content, r'<input type="checkbox" name="category" value="clothes">')
        self.assertNotContains(response, 'onchange=')

    def test_navbar_search_keeps_selected_categories_on_home(self):
        response = self.get_home(q='chem', category=['books', 'stationery'])
        content = response.content.decode()
        nav_form = content[content.index('class="nav-search__panel"'):]
        nav_form = nav_form[:nav_form.index('</form>')]

        self.assertIn('<input type="hidden" name="category" value="books">', nav_form)
        self.assertIn('<input type="hidden" name="category" value="stationery">', nav_form)
        self.assertIn('value="chem"', nav_form)

    def test_navbar_search_is_available_on_other_pages(self):
        response = self.client.get(reverse('login'))
        content = response.content.decode()

        self.assertIn('class="nav-search__panel" action="%s"' % reverse('home'), content)
        self.assertNotIn('<input type="hidden" name="category"', content)

    def test_removing_one_filter_keeps_the_rest(self):
        response = self.get_home(q='chem', category=['books', 'clothes'])
        remove_links = {
            active['value']: active['remove_url'] for active in response.context['active_filters']
        }

        self.assertEqual(remove_links['books'], reverse('home') + '?q=chem&category=clothes')
        self.assertEqual(remove_links['clothes'], reverse('home') + '?q=chem&category=books')
        self.assertEqual(
            response.context['clear_search_url'],
            reverse('home') + '?category=books&category=clothes',
        )
        self.assertEqual(response.context['clear_filters_url'], reverse('home') + '?q=chem')

    def test_empty_results_offer_targeted_resets(self):
        response = self.get_home(q='trombone', category='books')

        self.assertEqual(response.context['result_count'], 0)
        self.assertContains(response, 'No matching items')
        self.assertContains(response, 'href="%s"' % response.context['clear_search_url'])
        self.assertContains(response, 'href="%s"' % response.context['clear_filters_url'])
        self.assertContains(response, 'Show all items')

    def test_empty_site_shows_first_post_prompt(self):
        Item.objects.all().delete()

        response = self.get_home()

        self.assertContains(response, 'No posts yet.')

    def test_pagination_keeps_search_and_categories(self):
        for number in range(30):
            self.make_item(f'Revision book {number}', 'Chemistry practice', Item.Category.BOOKS)

        response = self.get_home(q='revision', category='books')

        self.assertEqual(response.context['result_count'], 30)
        self.assertEqual(len(response.context['items']), 24)
        self.assertContains(response, 'href="?q=revision&amp;category=books&amp;page=2"')

        second_page = self.get_home(q='revision', category='books', page=2)
        self.assertEqual(len(second_page.context['items']), 6)

    def test_overlong_search_text_is_truncated(self):
        response = self.get_home(q='a' * 500)

        self.assertEqual(len(response.context['query']), 100)


class ClaimTestMixin:
    """Shared users/item for the claim journey tests."""

    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username='owner', password='secure-password-123')
        self.claimant = User.objects.create_user(username='claimant', password='secure-password-123')
        self.other = User.objects.create_user(username='other-student', password='secure-password-123')
        self.outsider = User.objects.create_user(username='outsider', password='secure-password-123')
        self.item = Item.objects.create(
            owner=self.owner,
            title='Biology flashcards',
            description='Full set.',
            category=Item.Category.STATIONERY,
        )

    def claim(self, claimant=None, status=Claim.Status.PENDING, note='Please!'):
        return Claim.objects.create(
            item=self.item,
            claimant=claimant or self.claimant,
            status=status,
            note=note,
        )

    def reserve(self):
        self.item.status = Item.Status.RESERVED
        self.item.save(update_fields=['status', 'updated_at'])

    def detail(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('item_detail', kwargs={'pk': self.item.pk}))

    def act(self, user, claim, action, **data):
        self.client.force_login(user)
        return self.client.post(
            reverse('claim_update', kwargs={'pk': claim.pk, 'action': action}),
            data,
        )


class ItemDetailClaimPanelTests(ClaimTestMixin, TestCase):
    def test_other_students_see_the_claim_form(self):
        response = self.detail(self.claimant)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'action="%s"' % reverse('claim_create', kwargs={'pk': self.item.pk}))
        self.assertContains(response, 'Send claim')
        self.assertTrue(response.context['can_claim'])

    def test_owner_sees_management_panel_instead_of_claim_form(self):
        self.claim()

        response = self.detail(self.owner)

        self.assertNotContains(response, 'Send claim')
        self.assertContains(response, 'This is your listing')
        self.assertContains(response, '1 waiting for your decision')
        self.assertContains(response, reverse('my_posts'))

    def test_pending_claim_is_shown_with_a_cancel_button(self):
        claim = self.claim()

        response = self.detail(self.claimant)

        self.assertNotContains(response, 'Send claim')
        self.assertContains(response, 'Your claim')
        self.assertContains(response, reverse('claim_update', kwargs={'pk': claim.pk, 'action': 'cancel'}))

    def test_cancelled_claim_can_be_sent_again(self):
        self.claim(status=Claim.Status.CANCELLED)

        response = self.detail(self.claimant)

        self.assertContains(response, 'Claim it again')
        self.assertTrue(response.context['can_claim'])

    def test_invalid_note_is_shown_again_with_its_error(self):
        self.client.force_login(self.claimant)
        long_note = 'x' * 501

        response = self.client.post(
            reverse('claim_create', kwargs={'pk': self.item.pk}),
            {'note': long_note},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'listings/item_detail.html')
        self.assertIn('note', response.context['claim_form'].errors)
        self.assertContains(response, long_note)
        self.assertContains(response, 'id="id_note_error"')
        self.assertFalse(Claim.objects.exists())

    def test_items_without_photos_show_a_placeholder(self):
        response = self.detail(self.claimant)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No photos for this listing')

    def test_unavailable_item_explains_its_state(self):
        self.claim(status=Claim.Status.APPROVED)
        self.reserve()

        response = self.detail(self.owner)

        self.assertContains(response, 'This item is reserved for claimant')


class ItemVisibilityTests(ClaimTestMixin, TestCase):
    def test_reserved_item_is_visible_to_the_people_involved(self):
        self.claim(status=Claim.Status.APPROVED)
        self.claim(claimant=self.other, status=Claim.Status.DECLINED)
        self.reserve()

        for user in (self.owner, self.claimant, self.other):
            with self.subTest(user=user.username):
                self.assertEqual(self.detail(user).status_code, 200)

        self.assertEqual(self.detail(self.outsider).status_code, 404)

    def test_chat_participants_can_still_open_a_reserved_item(self):
        Conversation.objects.create(item=self.item, owner=self.owner, requester=self.outsider)
        self.reserve()

        self.assertEqual(self.detail(self.outsider).status_code, 200)

    def test_passed_on_item_stays_hidden_from_everyone_else(self):
        self.item.status = Item.Status.PASSED_ON
        self.item.save(update_fields=['status', 'updated_at'])

        self.assertEqual(self.detail(self.outsider).status_code, 404)
        self.assertEqual(self.detail(self.owner).status_code, 200)

    def test_unavailable_items_cannot_be_claimed(self):
        for status in (Item.Status.RESERVED, Item.Status.PASSED_ON):
            with self.subTest(status=status):
                self.item.status = status
                self.item.save(update_fields=['status', 'updated_at'])
                self.client.force_login(self.outsider)

                response = self.client.post(
                    reverse('claim_create', kwargs={'pk': self.item.pk}),
                    {'note': 'Me please'},
                    follow=True,
                )

                self.assertContains(response, 'This item is no longer available to claim.')
                self.assertFalse(Claim.objects.filter(claimant=self.outsider).exists())


class ClaimDecisionTests(ClaimTestMixin, TestCase):
    def test_owner_can_decline_a_pending_claim(self):
        claim = self.claim()

        response = self.act(self.owner, claim, 'decline')

        self.assertRedirects(response, reverse('my_posts'))
        claim.refresh_from_db()
        self.assertEqual(claim.status, Claim.Status.DECLINED)
        self.assertIsNotNone(claim.decided_at)

    def test_only_the_owner_can_decide(self):
        pending = self.claim()
        approved = self.claim(claimant=self.other, status=Claim.Status.APPROVED)

        for user, claim, action in (
            (self.claimant, pending, 'decline'),
            (self.outsider, pending, 'decline'),
            (self.outsider, approved, 'complete'),
            (self.claimant, approved, 'release'),
        ):
            with self.subTest(user=user.username, action=action):
                status_before = claim.status
                self.act(user, claim, action)
                claim.refresh_from_db()
                self.assertEqual(claim.status, status_before)

    def test_complete_requires_an_approved_claim(self):
        claim = self.claim()

        response = self.act(self.owner, claim, 'complete', next='/')

        self.assertRedirects(response, reverse('my_posts'))
        claim.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(claim.status, Claim.Status.PENDING)
        self.assertEqual(self.item.status, Item.Status.AVAILABLE)

    def test_owner_can_release_a_reservation(self):
        claim = self.claim(status=Claim.Status.APPROVED)
        self.reserve()

        response = self.act(self.owner, claim, 'release')

        self.assertRedirects(response, reverse('my_posts'))
        claim.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(claim.status, Claim.Status.DECLINED)
        self.assertEqual(self.item.status, Item.Status.AVAILABLE)

    def test_release_requires_an_approved_claim(self):
        claim = self.claim()

        self.act(self.owner, claim, 'release')

        claim.refresh_from_db()
        self.assertEqual(claim.status, Claim.Status.PENDING)

    def test_cancelling_an_approved_claim_reopens_the_item(self):
        claim = self.claim(status=Claim.Status.APPROVED)
        self.reserve()

        response = self.act(self.claimant, claim, 'cancel')

        self.assertRedirects(response, reverse('my_claims'))
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, Item.Status.AVAILABLE)

    def test_approving_when_the_item_is_already_reserved_is_rejected(self):
        self.claim(status=Claim.Status.APPROVED)
        late = self.claim(claimant=self.other)
        self.reserve()

        self.act(self.owner, late, 'approve')

        late.refresh_from_db()
        self.assertEqual(late.status, Claim.Status.PENDING)

    def test_unknown_actions_change_nothing(self):
        claim = self.claim()

        response = self.act(self.owner, claim, 'delete')

        self.assertRedirects(response, reverse('home'))
        claim.refresh_from_db()
        self.assertEqual(claim.status, Claim.Status.PENDING)

    def test_missing_claim_returns_404(self):
        self.client.force_login(self.owner)

        response = self.client.post(reverse('claim_update', kwargs={'pk': 999, 'action': 'approve'}))

        self.assertEqual(response.status_code, 404)

    def test_cancel_returns_to_a_safe_next_url_only(self):
        detail_url = reverse('item_detail', kwargs={'pk': self.item.pk})
        claim = self.claim()

        response = self.act(self.claimant, claim, 'cancel', next=detail_url)
        self.assertRedirects(response, detail_url)

        claim.status = Claim.Status.PENDING
        claim.save(update_fields=['status'])
        response = self.act(self.claimant, claim, 'cancel', next='https://evil.example/')
        self.assertRedirects(response, reverse('my_claims'))


class ClaimManagementPagesTests(ClaimTestMixin, TestCase):
    def test_my_posts_offers_approve_and_decline_for_pending_claims(self):
        claim = self.claim()
        self.client.force_login(self.owner)

        response = self.client.get(reverse('my_posts'))

        for action in ('approve', 'decline'):
            self.assertContains(response, reverse('claim_update', kwargs={'pk': claim.pk, 'action': action}))
        self.assertContains(response, reverse('chat:start_claimant_conversation', kwargs={'claim_id': claim.pk}))
        self.assertContains(response, '1 waiting for you')

    def test_my_posts_offers_complete_and_release_for_approved_claims(self):
        claim = self.claim(status=Claim.Status.APPROVED)
        self.reserve()
        self.client.force_login(self.owner)

        response = self.client.get(reverse('my_posts'))

        for action in ('complete', 'release'):
            self.assertContains(response, reverse('claim_update', kwargs={'pk': claim.pk, 'action': action}))
        self.assertNotContains(response, reverse('claim_update', kwargs={'pk': claim.pk, 'action': 'approve'}))

    def test_finished_claims_have_no_decision_buttons(self):
        claim = self.claim(status=Claim.Status.DECLINED)
        self.client.force_login(self.owner)

        response = self.client.get(reverse('my_posts'))

        for action in ('approve', 'decline', 'complete', 'release'):
            self.assertNotContains(response, reverse('claim_update', kwargs={'pk': claim.pk, 'action': action}))

    def test_my_claims_offers_cancel_only_for_active_claims(self):
        active = self.claim()
        other_item = Item.objects.create(
            owner=self.owner, title='Old tie', description='Tie', category=Item.Category.CLOTHES,
        )
        finished = Claim.objects.create(item=other_item, claimant=self.claimant, status=Claim.Status.DECLINED)
        self.client.force_login(self.claimant)

        response = self.client.get(reverse('my_claims'))

        self.assertContains(response, reverse('claim_update', kwargs={'pk': active.pk, 'action': 'cancel'}))
        self.assertNotContains(response, reverse('claim_update', kwargs={'pk': finished.pk, 'action': 'cancel'}))

    def test_my_posts_query_count_does_not_grow_with_items(self):
        self.client.force_login(self.owner)
        self.claim()

        with CaptureQueriesContext(connection) as one_item:
            self.client.get(reverse('my_posts'))

        for number in range(4):
            extra = Item.objects.create(
                owner=self.owner, title=f'Extra {number}', description='-', category=Item.Category.OTHER,
            )
            Claim.objects.create(item=extra, claimant=self.claimant)
            Claim.objects.create(item=extra, claimant=self.other)

        with CaptureQueriesContext(connection) as five_items:
            self.client.get(reverse('my_posts'))

        self.assertEqual(len(one_item.captured_queries), len(five_items.captured_queries))


@skipUnless(connection.vendor == 'postgresql', 'Row-level locking needs PostgreSQL')
class ClaimConcurrencyTests(TransactionTestCase):
    """Two approvals at once must reserve the item for exactly one student."""

    def test_simultaneous_approvals_reserve_for_one_claimant(self):
        User = get_user_model()
        owner = User.objects.create_user(username='owner', password='secure-password-123')
        first = User.objects.create_user(username='first', password='secure-password-123')
        second = User.objects.create_user(username='second', password='secure-password-123')
        item = Item.objects.create(owner=owner, title='Lab coat', description='-', category=Item.Category.CLOTHES)
        claims = [
            Claim.objects.create(item=item, claimant=first),
            Claim.objects.create(item=item, claimant=second),
        ]
        barrier = threading.Barrier(len(claims))
        results, errors = [], []

        def approve(claim_pk):
            try:
                client = Client()
                client.force_login(owner)
                barrier.wait(timeout=10)
                response = client.post(
                    reverse('claim_update', kwargs={'pk': claim_pk, 'action': 'approve'}),
                )
                results.append(response.status_code)
            except Exception as error:  # surfaced in the assertion below
                errors.append(error)
            finally:
                connection.close()

        threads = [threading.Thread(target=approve, args=(claim.pk,)) for claim in claims]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(errors, [])
        self.assertEqual(results, [302, 302])
        statuses = sorted(Claim.objects.filter(item=item).values_list('status', flat=True))
        self.assertEqual(statuses, [Claim.Status.APPROVED, Claim.Status.DECLINED])
        item.refresh_from_db()
        self.assertEqual(item.status, Item.Status.RESERVED)


# ---------------------------------------------------------------------------
# Phase 5: photo processing, the Post Item form page, listing cards
# ---------------------------------------------------------------------------

class TempMediaMixin:
    """Store uploads in a throwaway MEDIA_ROOT."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_directory = TemporaryDirectory()
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_directory.name)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        cls._media_directory.cleanup()
        super().tearDownClass()


def encoded_image(size, image_format, mode='RGB', color='coral', **save_options):
    buffer = BytesIO()
    Image.new(mode, size, color).save(buffer, format=image_format, **save_options)
    return buffer.getvalue()


class PhotoProcessingTests(TempMediaMixin, TestCase):
    """D6: new uploads lose their metadata and are capped at 2000px, format kept."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username='photographer', password='secure-password-123')
        self.client.force_login(self.user)

    def post_photo(self, name, data, content_type):
        return self.client.post(reverse('item_create'), {
            'title': 'Desk lamp',
            'description': 'Works well, warm light.',
            'category': Item.Category.DAILY_ESSENTIALS,
            'photos': [SimpleUploadedFile(name, data, content_type=content_type)],
        })

    def stored_image(self):
        photo = Item.objects.get(title='Desk lamp').photos.get()
        with photo.image.open('rb') as handle:
            image = Image.open(BytesIO(handle.read()))
            image.load()
        return photo, image

    def test_location_data_and_comments_are_removed_and_orientation_applied(self):
        from PIL import ExifTags

        exif = Image.Exif()
        exif[ExifTags.Base.Orientation] = 6  # stored sideways, displayed rotated
        exif[ExifTags.Base.Make] = 'TestPhone'
        exif[ExifTags.IFD.GPSInfo] = {
            ExifTags.GPS.GPSLatitudeRef: 'N',
            ExifTags.GPS.GPSLatitude: (1.0, 22.0, 33.0),
            ExifTags.GPS.GPSLongitudeRef: 'E',
            ExifTags.GPS.GPSLongitude: (103.0, 49.0, 10.0),
        }
        data = encoded_image((3000, 1000), 'JPEG', exif=exif, comment=b'hostel room 12')

        response = self.post_photo('IMG_0001.jpg', data, 'image/jpeg')

        self.assertEqual(response.status_code, 302)
        photo, image = self.stored_image()
        self.assertEqual(image.format, 'JPEG')
        self.assertTrue(photo.image.name.endswith('.jpg'))
        self.assertEqual(dict(image.getexif()), {})
        self.assertNotIn('exif', image.info)
        self.assertNotIn('comment', image.info)
        # Rotated upright (portrait) and capped at 2000px on the long edge.
        self.assertEqual(image.size, (667, 2000))

    def test_large_png_is_capped_and_stays_png(self):
        data = encoded_image((2400, 1200), 'PNG', mode='RGBA', color=(10, 20, 30, 128))

        self.post_photo('diagram.png', data, 'image/png')

        photo, image = self.stored_image()
        self.assertEqual(image.format, 'PNG')
        self.assertEqual(image.mode, 'RGBA')
        self.assertEqual(image.size, (2000, 1000))
        self.assertTrue(photo.image.name.endswith('.png'))

    def test_small_webp_keeps_format_and_size(self):
        data = encoded_image((800, 600), 'WEBP')

        self.post_photo('lamp.webp', data, 'image/webp')

        photo, image = self.stored_image()
        self.assertEqual(image.format, 'WEBP')
        self.assertEqual(image.size, (800, 600))
        self.assertTrue(photo.image.name.endswith('.webp'))

    def test_file_extension_follows_the_real_format(self):
        data = encoded_image((300, 200), 'PNG')

        self.post_photo('actually-a-png.jpg', data, 'image/jpeg')

        photo, image = self.stored_image()
        self.assertEqual(image.format, 'PNG')
        self.assertTrue(photo.image.name.endswith('.png'))

    def test_unreadable_photo_is_a_form_error_not_a_crash(self):
        full = encoded_image((400, 300), 'JPEG', quality=95)
        truncated = full[: len(full) // 2]

        response = self.post_photo('broken.jpg', truncated, 'image/jpeg')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Item.objects.count(), 0)
        self.assertIn('could not be read', response.context['form'].errors['photos'][0])

    def test_upload_limits_are_unchanged(self):
        from . import forms as listing_forms

        self.assertEqual(listing_forms.MAX_PHOTO_COUNT, 5)
        self.assertEqual(listing_forms.MAX_PHOTO_SIZE, 5 * 1024 * 1024)
        self.assertEqual(listing_forms.MAX_IMAGE_PIXELS, 25_000_000)
        self.assertEqual(listing_forms.SUPPORTED_IMAGE_FORMATS, {'JPEG', 'PNG', 'WEBP'})


class ItemFormPageTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='poster2', password='secure-password-123')
        self.client.force_login(self.user)

    def test_form_is_grouped_and_explains_the_photo_rules(self):
        response = self.client.get(reverse('item_create'))

        self.assertContains(response, '<legend class="form-card__section">About the item</legend>', html=True)
        self.assertContains(response, '<legend class="form-card__section">Photos</legend>', html=True)
        self.assertContains(response, '<option value="" selected>Choose a category</option>', html=True)
        self.assertContains(response, 'data-max-files="5"')
        self.assertContains(response, 'data-max-bytes="5242880"')
        self.assertContains(response, 'id="id_photos_helptext"')
        self.assertContains(response, 'aria-describedby="id_photos_helptext"')
        self.assertContains(response, 'data-submit-once')
        self.assertNotContains(response, 'data-photo-reselect')

    def test_typed_text_is_kept_and_photos_must_be_added_again_after_an_error(self):
        response = self.client.post(reverse('item_create'), {
            'title': '',
            'description': 'Barely used graphing calculator.',
            'category': Item.Category.STATIONERY,
            'photos': [SimpleUploadedFile('calc.png', encoded_image((60, 40), 'PNG'), content_type='image/png')],
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Item.objects.count(), 0)
        self.assertContains(response, 'Barely used graphing calculator.')
        self.assertContains(response, '<option value="stationery" selected>Stationery</option>', html=True)
        self.assertContains(response, 'Enter a title.')
        self.assertContains(response, 'data-photo-reselect')

    def test_required_messages_are_specific(self):
        response = self.client.post(reverse('item_create'), {})

        errors = response.context['form'].errors
        self.assertEqual(errors['title'], ['Enter a title.'])
        self.assertEqual(errors['description'], ['Add a short description.'])
        self.assertEqual(errors['category'], ['Choose a category.'])
        self.assertEqual(errors['photos'], ['Add at least one photo.'])


class ItemCardTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username='card-owner', password='secure-password-123')
        self.item = Item.objects.create(
            owner=self.owner,
            title='A very long title ' * 8,
            description='Description',
            category=Item.Category.BOOKS,
        )
        ItemPhoto.objects.create(
            item=self.item,
            image=SimpleUploadedFile('cover.png', encoded_image((40, 30), 'PNG'), content_type='image/png'),
            position=0,
        )

    def test_card_links_its_title_and_lazy_loads_the_cover(self):
        response = self.client.get(reverse('home'))
        detail_url = reverse('item_detail', kwargs={'pk': self.item.pk})

        self.assertContains(response, f'<a class="item-card__link" href="{detail_url}">')
        self.assertContains(response, 'loading="lazy"')
        self.assertNotContains(response, 'aria-label="View')

    def test_card_has_no_dead_favourite_button(self):
        response = self.client.get(reverse('home'))

        self.assertNotContains(response, 'item-card__fav')
        self.assertNotContains(response, 'icon--heart')


class MultiPictureJpegTests(TempMediaMixin, TestCase):
    """Phone JPEGs with extra pictures attached (Pillow: "MPO") are accepted
    and stored as a plain JPEG of the main picture."""

    def test_mpo_photo_is_accepted_and_stored_as_jpeg(self):
        user = get_user_model().objects.create_user(username='camera-user', password='secure-password-123')
        self.client.force_login(user)
        main = Image.new('RGB', (1200, 900), 'coral')
        extra = Image.new('RGB', (300, 200), 'navy')
        buffer = BytesIO()
        main.save(buffer, format='MPO', save_all=True, append_images=[extra])
        self.assertEqual(Image.open(BytesIO(buffer.getvalue())).format, 'MPO')

        response = self.client.post(reverse('item_create'), {
            'title': 'Camera bag',
            'description': 'Fits a small camera.',
            'category': Item.Category.OTHER,
            'photos': [SimpleUploadedFile('IMG_1234.jpg', buffer.getvalue(), content_type='image/jpeg')],
        })

        self.assertEqual(response.status_code, 302)
        photo = Item.objects.get(title='Camera bag').photos.get()
        self.assertTrue(photo.image.name.endswith('.jpg'))
        with photo.image.open('rb') as handle:
            stored = Image.open(BytesIO(handle.read()))
            self.assertEqual(stored.format, 'JPEG')
            self.assertEqual(stored.size, (1200, 900))
            self.assertEqual(getattr(stored, 'n_frames', 1), 1)
