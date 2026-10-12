from django import forms

from .models import Message


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ['body']
        widgets = {
            'body': forms.Textarea(
                attrs={
                    'rows': 3,
                    'maxlength': 2000,
                    'placeholder': 'Write a message...',
                },
            ),
        }

    def clean_body(self):
        body = self.cleaned_data['body'].strip()
        if not body:
            raise forms.ValidationError('Enter a message.')
        return body

