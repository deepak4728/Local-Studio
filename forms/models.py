import uuid
from django.conf import settings
from django.db import models
from django.utils.text import slugify
from decimal import Decimal


class DynamicForm(models.Model):
    VISIBILITY_PUBLIC = "public"
    VISIBILITY_ORGANIZATION = "organization"
    VISIBILITY_RESTRICTED = "restricted"
    VISIBILITY_CHOICES = (
        (VISIBILITY_PUBLIC, "Anyone with the link"),
        (VISIBILITY_ORGANIZATION, "Organization members"),
        (VISIBILITY_RESTRICTED, "Specific accounts"),
    )
    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = ((STATUS_DRAFT, "Draft"), (STATUS_ACTIVE, "Active"), (STATUS_ARCHIVED, "Archived"))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="forms")
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=180)
    description = models.TextField(blank=True, default="")
    purpose = models.CharField(max_length=120, blank=True, default="")
    schema = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    visibility = models.CharField(max_length=16, choices=VISIBILITY_CHOICES, default=VISIBILITY_ORGANIZATION)
    allowed_users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="shared_orgforms")
    allowed_groups = models.ManyToManyField("organizations.OrganizationGroup", blank=True, related_name="forms")
    editors = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="editable_orgforms")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("organization", "slug"), name="unique_form_slug_per_org")]
        ordering = ("-updated_at",)

    def save(self, *args, **kwargs):
        from .services import normalize_schema
        if self.schema:
            self.schema = normalize_schema(self.schema, self.organization)
        if not self.slug:
            base = slugify(self.title)[:150] or "form"
            if base in {"settings", "people", "menu", "submissions", "forms"}:
                base += "-form"
            candidate = base
            counter = 2
            while DynamicForm.objects.filter(organization=self.organization, slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{counter}"
                counter += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class FormSubmission(models.Model):
    STATUS_SUBMITTED = "submitted"
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = (
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_PENDING, "Pending review"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    )

    form = models.ForeignKey(DynamicForm, on_delete=models.PROTECT, related_name="submissions")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="submissions")
    data = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_SUBMITTED)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    respondent_name = models.CharField(max_length=200, blank=True, default="")
    respondent_email = models.EmailField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("organization", "created_at"))]


class SubmissionAttachment(models.Model):
    submission = models.ForeignKey(FormSubmission, on_delete=models.CASCADE, related_name="attachments")
    field_id = models.CharField(max_length=80)
    file = models.FileField(upload_to="submission-files/%Y/%m/")
    original_name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")


class Catalog(models.Model):
    organization = models.ForeignKey("organizations.Organization", null=True, blank=True, on_delete=models.CASCADE, related_name="catalogs")
    name = models.CharField(max_length=200, default="Items")
    description = models.TextField(blank=True, default="")
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def for_organization(cls, organization):
        catalog = cls.objects.filter(organization=organization).order_by("pk").first()
        return catalog or cls.objects.create(organization=organization, name=organization.name)

class CatalogItem(models.Model):
    catalog = models.ForeignKey(
        Catalog,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="items",
    )
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, default="General")
    description = models.TextField(blank=True, default="")
    barcode = models.CharField(max_length=128, blank=True, default="", db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return self.name


class ItemSelection(models.Model):
    submission = models.ForeignKey("FormSubmission", null=True, blank=True, on_delete=models.SET_NULL, related_name="item_selections")
    field_id = models.CharField(max_length=80, blank=True, default="")
    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_PREPARING = "preparing"
    STATUS_READY = "ready"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_PREPARING, "Preparing"),
        (STATUS_READY, "Ready"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    )

    catalog = models.ForeignKey(Catalog, on_delete=models.CASCADE, related_name="selections")
    customer_name = models.CharField(max_length=200, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)
    # Retain historical processing and payment state for migrated selections.
    PAYMENT_PENDING = "pending"
    PAYMENT_AUTHORIZED = "authorized"
    PAYMENT_PAID = "paid"
    PAYMENT_FAILED = "failed"
    PAYMENT_REFUNDED = "refunded"
    PAYMENT_STATUS_CHOICES = (
        (PAYMENT_PENDING, "Pending"),
        (PAYMENT_AUTHORIZED, "Authorized"),
        (PAYMENT_PAID, "Paid"),
        (PAYMENT_FAILED, "Failed"),
        (PAYMENT_REFUNDED, "Refunded"),
    )
    payment_status = models.CharField(
        max_length=32, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_PENDING
    )
    fulfillment_status = models.CharField(
        max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    REVIEW_PENDING = "pending"
    REVIEW_APPROVED = "approved"
    REVIEW_REJECTED = "rejected"
    REVIEW_STATUS_CHOICES = (
        (REVIEW_PENDING, "Pending review"),
        (REVIEW_APPROVED, "Approved"),
        (REVIEW_REJECTED, "Rejected"),
    )
    review_status = models.CharField(
        max_length=32, choices=REVIEW_STATUS_CHOICES, default=REVIEW_PENDING
    )
    review_note = models.TextField(blank=True, default="")
    reviewed_by = models.CharField(max_length=160, blank=True, default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def recalculate_totals(self):
        subtotal = sum(
            (item.line_total for item in self.items.all()),
            Decimal("0.00"),
        )
        discount = subtotal * (self.catalog.discount_percent / Decimal("100")) if self.catalog.discount_percent else Decimal("0.00")
        tax = subtotal * (self.catalog.tax_rate / Decimal("100")) if self.catalog.tax_rate else Decimal("0.00")
        total = subtotal - discount + tax
        self.subtotal = subtotal.quantize(Decimal("0.01"))
        self.discount = discount.quantize(Decimal("0.01"))
        self.tax = tax.quantize(Decimal("0.01"))
        self.total = total.quantize(Decimal("0.01"))
        self.save(update_fields=["subtotal", "discount", "tax", "total", "updated_at"])

    def __str__(self):
        return f"ItemSelection #{self.pk}"


class SelectionLine(models.Model):
    selection = models.ForeignKey(ItemSelection, on_delete=models.CASCADE, related_name="items")
    catalog_item = models.ForeignKey(CatalogItem, on_delete=models.PROTECT, related_name="selection_lines")
    name = models.CharField(max_length=200, blank=True, default="")
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        unit_price = Decimal(str(self.unit_price))
        self.line_total = (unit_price * self.quantity).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity} x {self.catalog_item.name}"
