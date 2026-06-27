from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm as _PasswordChangeForm

User = get_user_model()


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email', 'phone_number']
        widgets = {
            'first_name':   forms.TextInput(attrs={'placeholder': 'First name',    'class': 'form-input'}),
            'last_name':    forms.TextInput(attrs={'placeholder': 'Last name',     'class': 'form-input'}),
            'username':     forms.TextInput(attrs={'placeholder': 'Username',      'class': 'form-input'}),
            'email':        forms.EmailInput(attrs={'placeholder': 'Email address','class': 'form-input'}),
            'phone_number': forms.TextInput(attrs={'placeholder': '+679 700 0000', 'class': 'form-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['phone_number'].required = False

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        qs = User.objects.filter(email=email).exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_username(self):
        username = self.cleaned_data['username']
        qs = User.objects.filter(username=username).exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("This username is already taken.")
        return username


class PasswordChangeForm(_PasswordChangeForm):
    """Thin wrapper so templates reference a consistent name."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('autocomplete', 'off')
            field.widget.attrs['class'] = 'form-input'
