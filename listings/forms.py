from django import forms
from django.core.exceptions import ValidationError

from .models import Claim, Item


MAX_PHOTO_COUNT = 5
MAX_PHOTO_SIZE = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
SUPPORTED_IMAGE_FORMATS = {'JPEG', 'PNG', 'WEBP'}


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
            attrs={'accept': 'image/jpeg,image/png,image/webp'},
        ),
        help_text='Add 1 to 5 JPEG, PNG, or WebP photos. Each photo can be up to 5 MB.',
    )

    class Meta:
        model = Item
        fields = ['title', 'description', 'category']

    field_order = ['title', 'description', 'category', 'photos']

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

        return photos


class ClaimForm(forms.ModelForm):
    class Meta:
        model = Claim
        fields = ['note']
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
