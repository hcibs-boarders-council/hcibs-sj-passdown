from django import forms
from django.contrib.auth import get_user_model
from django.core.validators import validate_email


class AccountDetailsForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ['first_name', 'last_name', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={'autocomplete': 'given-name'}),
            'last_name': forms.TextInput(attrs={'autocomplete': 'family-name'}),
            'email': forms.EmailInput(attrs={'autocomplete': 'email'}),
        }

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if email:
            validate_email(email)
        return email
