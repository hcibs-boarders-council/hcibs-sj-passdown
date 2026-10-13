from django import forms
from django.core.exceptions import ValidationError

from .images import PhotoProcessingError, prepare_photo
from .models import Claim, Item


MAX_PHOTO_COUNT = 5
MAX_PHOTO_SIZE = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
SUPPORTED_IMAGE_FORMATS = {'JPEG', 'PNG', 'WEBP'}
ACCEPTED_IMAGE_TYPES = 'image/jpeg,image/png,image/webp'


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    default_error_messages = {
        'invalid_image': 'Upload a valid JPEG, PNG, or WebP image.',
        'required': 'Add at least one photo.',
    }

    def clean(self, data, initial=None):
        if not data:
            return super().clean(data, initial)

        files = data if isinstance(data, (list, tuple)) else [data]
        cleaned_files = []
        errors = []

        for uploaded_file in files:
            try:
                cleaned_files.append(super().clean(uploaded_file, initial))
            except ValidationError as error:
                errors.extend(error.error_list)

        if errors:
            raise ValidationError(errors)

        return cleaned_files


class ItemForm(forms.ModelForm):
    photos = MultipleImageField(
        widget=MultipleFileInput(
            attrs={
                'accept': ACCEPTED_IMAGE_TYPES,
                # Read by item_form.js for early warnings; the server re-checks.
                'data-max-files': MAX_PHOTO_COUNT,
                'data-max-bytes': MAX_PHOTO_SIZE,
            },
        ),
        help_text='Add 1 to 5 photos: JPEG, PNG, or WebP, up to 5 MB each. The first photo is the cover.',
    )

    class Meta:
        model = Item
        fields = ['title', 'description', 'category']
        labels = {
            'title': 'Title',
            'description': 'Description',
            'category': 'Category',
        }
        help_texts = {
            'title': 'Be specific, e.g. “H2 Chemistry ten-year series (2019–2023)”.',
            'description': 'Condition, size or edition, and anything a junior should know before claiming.',
        }
        error_messages = {
            'title': {'required': 'Enter a title.'},
            'description': {'required': 'Add a short description.'},
            'category': {'required': 'Choose a category.'},
        }
        widgets = {
            'title': forms.TextInput(attrs={
                'placeholder': 'What are you passing down?',
                'autocomplete': 'off',
            }),
            'description': forms.Textarea(attrs={
                'rows': 5,
                'placeholder': 'Lightly used, a few pencil notes inside. Collect from Block B.',
            }),
        }

    field_order = ['title', 'category', 'description', 'photos']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A friendlier empty choice than Django's "---------".
        self.fields['category'].choices = [('', 'Choose a category'), *Item.Category.choices]

    def clean_photos(self):
        photos = self.cleaned_data['photos']

        if len(photos) > MAX_PHOTO_COUNT:
            raise ValidationError('You can upload up to 5 photos.')

        total_size = 0
        for photo in photos:
            total_size += photo.size

            if photo.size > MAX_PHOTO_SIZE:
                raise ValidationError('Each photo must be 5 MB or smaller.')

            image = getattr(photo, 'image', None)
            image_format = getattr(image, 'format', None)
            if image_format not in SUPPORTED_IMAGE_FORMATS:
                raise ValidationError('Upload only JPEG, PNG, or WebP photos.')

            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValidationError('Each photo must be no larger than 25 megapixels.')

        if total_size > MAX_PHOTO_COUNT * MAX_PHOTO_SIZE:
            raise ValidationError('Your combined photo upload must be 25 MB or smaller.')

        # Strip location/metadata and cap the size (see listings/images.py).
        # Done here so an unreadable photo becomes a form error, not a crash.
        try:
            return [prepare_photo(photo) for photo in photos]
        except PhotoProcessingError:
            raise ValidationError('One of your photos could not be read. Try saving it again or choose a different photo.')


class ClaimForm(forms.ModelForm):
    class Meta:
        model = Claim
        fields = ['note']
        labels = {'note': 'Note for the owner'}
        help_texts = {'note': 'For example, when you could collect it.'}
        widgets = {
            'note': forms.Textarea(
                attrs={
                    'rows': 3,
                    'maxlength': 500,
                    'placeholder': 'Add collection timing or hostel notes if helpful.',
                },
            ),
        }

    def clean_note(self):
        return self.cleaned_data['note'].strip()
