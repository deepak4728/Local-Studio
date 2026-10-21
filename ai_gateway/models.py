from django.conf import settings
from django.db import models


class AIConfiguration(models.Model):
    PROVIDER_LOCAL = "local"
    PROVIDER_CLOUD = "cloud"
    PROVIDER_CHOICES = ((PROVIDER_LOCAL, "Local Ollama"), (PROVIDER_CLOUD, "Cloud API"))
    organization = models.OneToOneField("organizations.Organization", null=True, blank=True, on_delete=models.CASCADE, related_name="ai_configuration")
    preferred_provider = models.CharField(max_length=16, choices=PROVIDER_CHOICES, default=PROVIDER_LOCAL)
    cloud_provider = models.CharField(max_length=50, blank=True, default="")
    default_model = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def effective_provider(self):
        return self.preferred_provider or self.PROVIDER_LOCAL

    @classmethod
    def get_or_create_default(cls):
        profile = cls.objects.filter(organization__isnull=True).order_by("pk").first()
        return profile or cls.objects.create(default_model=settings.OLLAMA_DEFAULT_MODEL or "")

    @classmethod
    def for_organization(cls, organization):
        existing = cls.objects.filter(organization=organization).first()
        if existing:
            return existing
        default = cls.get_or_create_default()
        return cls.objects.create(organization=organization, preferred_provider=default.preferred_provider, cloud_provider=default.cloud_provider, default_model=default.default_model)

class LocalModelProfile(models.Model):
    INPUT_TEXT = "text"
    INPUT_MULTIMODAL = "multimodal"
    INPUT_MODE_CHOICES = (
        (INPUT_TEXT, "Text only"),
        (INPUT_MULTIMODAL, "Text and images"),
    )

    name = models.CharField(max_length=256, unique=True)
    context_window = models.PositiveIntegerField(default=4096)
    supports_thinking = models.BooleanField(default=False)
    think_enabled = models.BooleanField(default=False)
    supports_vision = models.BooleanField(default=False)
    input_mode = models.CharField(
        max_length=16,
        choices=INPUT_MODE_CHOICES,
        default=INPUT_TEXT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
