from django.conf import settings
from django.db import models


class UserPortfolio(models.Model):
    """Private profile facts and preferences used for user-directed form assistance."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="orgforms_portfolio")
    phone_number = models.CharField(max_length=40, blank=True, default="")
    profile_data = models.JSONField(default=dict, blank=True)
    use_for_form_assistance = models.BooleanField(default=False)
    auto_update_from_submissions = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class PersonalDocument(models.Model):
    KIND_CHOICES = (("resume", "Resume / CV"), ("identity", "Identity document"), ("license", "Driver license"), ("tax", "Tax document"), ("other", "Other"))
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="personal_documents")
    title = models.CharField(max_length=160)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default="other")
    file = models.FileField(upload_to="personal-documents/%Y/%m/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
