import re
from django.core.validators import validate_email
from django import forms
from django.contrib.auth import get_user_model
from forms.models import DynamicForm


class FormAccessSettingsForm(forms.Form):
    visibility = forms.ChoiceField(choices=DynamicForm.VISIBILITY_CHOICES)
    access_emails = forms.CharField(required=False, widget=forms.Textarea)

    def clean(self):
        cleaned = super().clean()
        emails = sorted(set(part.lower() for part in re.split(r"[\s,;]+", cleaned.get("access_emails", "").strip()) if part))
        self.allowed_accounts = []
        if cleaned.get("visibility") != DynamicForm.VISIBILITY_RESTRICTED:
            return cleaned
        if not emails:
            self.add_error("access_emails", "Add at least one account email for a restricted form.")
            return cleaned
        if len(emails) > 100:
            self.add_error("access_emails", "Share with up to 100 accounts at a time.")
            return cleaned
        for email in emails:
            try:
                validate_email(email)
            except forms.ValidationError:
                self.add_error("access_emails", f"Enter a valid email address: {email}")
                continue
            matches = list(get_user_model().objects.filter(email__iexact=email, is_active=True)[:2])
            if len(matches) != 1:
                self.add_error("access_emails", f"{email} must have a unique active OrgForms account before sharing.")
            else:
                self.allowed_accounts.append(matches[0])
        return cleaned
