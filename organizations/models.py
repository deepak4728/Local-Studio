from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Organization(models.Model):
    TYPE_GENERIC = "generic"
    TYPE_RESTAURANT = "restaurant"
    TYPE_CAFE = "cafe"
    TYPE_HOSPITALITY = "hospitality"
    TYPE_RESTAURANT_SERVICE = "restaurant_service"
    TYPE_RETAIL = "retail"
    TYPE_HEALTHCARE = "healthcare"
    TYPE_EDUCATION = "education"
    TYPE_PROFESSIONAL_SERVICES = "professional_services"
    TYPE_CHOICES = (
        (TYPE_GENERIC, "General business"),
        (TYPE_RESTAURANT, "Restaurant"),
        (TYPE_CAFE, "Cafe"),
        (TYPE_HOSPITALITY, "Hospitality"),
        (TYPE_RESTAURANT_SERVICE, "Restaurant service"),
        (TYPE_RETAIL, "Retail"),
        (TYPE_HEALTHCARE, "Healthcare"),
        (TYPE_EDUCATION, "Education"),
        (TYPE_PROFESSIONAL_SERVICES, "Professional services"),
    )

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=180, unique=True)
    description = models.TextField(blank=True, default="")
    purpose = models.CharField(max_length=80, blank=True, default="")
    business_type = models.CharField(max_length=24, choices=TYPE_CHOICES, default=TYPE_GENERIC)
    is_archived = models.BooleanField(default=False)
    profile_data = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_organizations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "id")

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:150] or "organization"
            candidate = base
            counter = 2
            while Organization.objects.exclude(pk=self.pk).filter(slug=candidate).exists():
                candidate = f"{base}-{counter}"
                counter += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @property
    def category_display(self):
        return (self.profile_data or {}).get("custom_category") or self.get_business_type_display()


class OrganizationMembership(models.Model):
    ROLE_ADMIN = "admin"
    ROLE_MANAGER = "manager"
    ROLE_MEMBER = "member"
    ROLE_CHOICES = (
        (ROLE_ADMIN, "Admin"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_MEMBER, "Member"),
    )

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="organization_memberships")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("organization", "user"), name="unique_org_membership")]
        ordering = ("organization__name", "user__email")

    def __str__(self):
        return f"{self.user} — {self.organization} ({self.role})"


class OrganizationGroup(models.Model):
    """Reusable team alias that can be granted access to organization forms."""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="groups")
    name = models.CharField(max_length=100)
    alias = models.SlugField(max_length=100)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="organization_groups")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)
        constraints = [models.UniqueConstraint(fields=("organization", "alias"), name="unique_org_group_alias")]

    def __str__(self):
        return f"{self.organization}: {self.name} (@{self.alias})"


class OrganizationDocument(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="organization-documents/%Y/%m/")
    extracted_text = models.TextField(blank=True, default="")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
