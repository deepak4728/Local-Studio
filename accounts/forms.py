from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


class RegistrationForm(forms.Form):
    # The built-in User model stores the email login in its 150-character username.
    email = forms.EmailField(max_length=150)
    password1 = forms.CharField(widget=forms.PasswordInput, min_length=12, label="Password")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm password")

    def clean_password1(self):
        password = self.cleaned_data["password1"]
        email = self.cleaned_data.get("email", "")
        user_model = get_user_model()
        candidate = user_model(username=email, email=email)
        try:
            validate_password(password, user=candidate)
        except ValidationError as error:
            raise forms.ValidationError(error.messages) from error
        return password

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        User = get_user_model()
        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account already exists for this email.")
        return email

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password1") != cleaned.get("password2"):
            self.add_error("password2", "The passwords do not match.")
        return cleaned


class AccountDetailsForm(forms.ModelForm):
    email = forms.EmailField(max_length=150)

    class Meta:
        model = get_user_model()
        fields = ("first_name", "last_name", "email")
        widgets = {
            "first_name": forms.TextInput(attrs={"autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs={"autocomplete": "family-name"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
        }

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        user_model = get_user_model()
        other_accounts = user_model.objects.exclude(pk=self.instance.pk)
        if other_accounts.filter(email__iexact=email).exists() or other_accounts.filter(username__iexact=email).exists():
            raise forms.ValidationError("This email address is already used by another account.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        # The sign-in form accepts email and authenticates against username.
        user.username = self.cleaned_data["email"]
        if commit:
            user.save()
            self.save_m2m()
        return user
