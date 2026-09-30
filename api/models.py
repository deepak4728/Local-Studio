import hashlib
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models


class BusinessProfile(models.Model):
    PROVIDER_LOCAL = "local"
    PROVIDER_CLOUD = "cloud"
    PROVIDER_CHOICES = (
        (PROVIDER_LOCAL, "Local Ollama"),
        (PROVIDER_CLOUD, "Cloud API"),
    )

    BUSINESS_TYPE_GENERIC = "generic"
    BUSINESS_TYPE_RESTAURANT = "restaurant"
    BUSINESS_TYPE_CHOICES = (
        (BUSINESS_TYPE_GENERIC, "Generic business"),
        (BUSINESS_TYPE_RESTAURANT, "Restaurant"),
    )

    business_name = models.CharField(max_length=200, default="My Business")
    business_type = models.CharField(
        max_length=32,
        choices=BUSINESS_TYPE_CHOICES,
        default=BUSINESS_TYPE_GENERIC,
    )
    preferred_provider = models.CharField(
        max_length=16,
        choices=PROVIDER_CHOICES,
        default=PROVIDER_LOCAL,
    )
    cloud_provider = models.CharField(max_length=50, blank=True, default="")
    default_model = models.CharField(max_length=128, blank=True, default="")
    description = models.TextField(blank=True, default="")
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "business profile"
        verbose_name_plural = "business profiles"

    @property
    def effective_provider(self):
        return self.preferred_provider or self.PROVIDER_LOCAL

    @classmethod
    def get_or_create_default(cls):
        profile, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "business_name": "My Business",
                "business_type": cls.BUSINESS_TYPE_GENERIC,
                "preferred_provider": cls.PROVIDER_LOCAL,
                "default_model": settings.OLLAMA_DEFAULT_MODEL or "",
                "description": "",
                "discount_percent": Decimal("0.00"),
                "tax_rate": Decimal("0.00"),
            },
        )
        if not profile.default_model and settings.OLLAMA_DEFAULT_MODEL:
            profile.default_model = settings.OLLAMA_DEFAULT_MODEL
            profile.save(update_fields=["default_model"])
        return profile


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


class ChatConversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_hash = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=160, default="New conversation")
    model = models.CharField(max_length=256, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    @staticmethod
    def hash_owner(owner_token):
        return hashlib.sha256(owner_token.encode("utf-8")).hexdigest()


class ChatMessage(models.Model):
    ROLE_SYSTEM = "system"
    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_CHOICES = (
        (ROLE_SYSTEM, "System"),
        (ROLE_USER, "User"),
        (ROLE_ASSISTANT, "Assistant"),
    )

    conversation = models.ForeignKey(
        ChatConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    content = models.TextField()
    images = models.JSONField(default=list, blank=True)
    memory_count = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class ChatMemoryPreference(models.Model):
    owner_hash = models.CharField(max_length=64, unique=True)
    enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class ChatMemory(models.Model):
    CATEGORY_PREFERENCE = "preference"
    CATEGORY_PROJECT = "project"
    CATEGORY_FACT = "fact"
    CATEGORY_CHOICES = (
        (CATEGORY_PREFERENCE, "Preference"),
        (CATEGORY_PROJECT, "Project"),
        (CATEGORY_FACT, "Fact"),
    )

    owner_hash = models.CharField(max_length=64, db_index=True)
    content = models.TextField()
    category = models.CharField(
        max_length=16,
        choices=CATEGORY_CHOICES,
        default=CATEGORY_FACT,
    )
    source_conversation = models.ForeignKey(
        ChatConversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memories",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=("owner_hash", "content"),
                name="unique_chat_memory_per_owner",
            )
        ]


class MenuItem(models.Model):
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


class Order(models.Model):
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

    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="orders")
    customer_name = models.CharField(max_length=200, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)
    # ``status`` is retained for clients written before connected ordering.  New
    # code should use the independent lifecycle fields below.
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
        discount = subtotal * (self.business.discount_percent / Decimal("100")) if self.business.discount_percent else Decimal("0.00")
        tax = subtotal * (self.business.tax_rate / Decimal("100")) if self.business.tax_rate else Decimal("0.00")
        total = subtotal - discount + tax
        self.subtotal = subtotal.quantize(Decimal("0.01"))
        self.discount = discount.quantize(Decimal("0.01"))
        self.tax = tax.quantize(Decimal("0.01"))
        self.total = total.quantize(Decimal("0.01"))
        self.save(update_fields=["subtotal", "discount", "tax", "total", "updated_at"])

    def __str__(self):
        return f"Order #{self.pk}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    menu_item = models.ForeignKey(MenuItem, on_delete=models.PROTECT, related_name="order_items")
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
        return f"{self.quantity} x {self.menu_item.name}"
