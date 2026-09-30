"""Connected restaurant primitives.

The original menu/order models live in :mod:`api.models` for migration
compatibility.  Connected-restaurant ownership and security data lives here.
"""
import ipaddress
import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.core import signing
from django.db import models
from django.utils import timezone

from api.models import BusinessProfile, MenuItem, Order, OrderItem


class RestaurantTable(models.Model):
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="restaurant_tables")
    name = models.CharField(max_length=120)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def sign(self, purpose="table", max_age=None):
        value = {"table": str(self.token), "business": self.business_id, "purpose": purpose}
        return signing.dumps(value, salt="restaurant.table.v1")

    @classmethod
    def verify(cls, value, max_age=None):
        data = signing.loads(value, salt="restaurant.table.v1", max_age=max_age)
        table = cls.objects.get(token=data["table"], business_id=data["business"], is_active=True)
        if data.get("purpose") != "table":
            raise signing.BadSignature("invalid table purpose")
        return table


class DiningSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    table = models.ForeignKey(RestaurantTable, on_delete=models.CASCADE, related_name="sessions")
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_valid(self):
        return self.revoked_at is None and self.expires_at > timezone.now() and self.table.is_active

    def sign(self):
        return signing.dumps(
            {"session": str(self.id), "table": str(self.table.token), "business": self.table.business_id},
            salt="restaurant.session.v1",
        )

    @classmethod
    def verify(cls, value, max_age=None):
        data = signing.loads(value, salt="restaurant.session.v1", max_age=max_age)
        session = cls.objects.select_related("table").get(
            pk=data["session"], table__token=data["table"], table__business_id=data["business"]
        )
        if not session.is_valid:
            raise signing.BadSignature("expired or revoked dining session")
        return session

    def is_trusted_for(self, request):
        """A signed, live table session is trusted independently of network."""
        return self.is_valid


class RestaurantNetworkPolicy(models.Model):
    business = models.OneToOneField(BusinessProfile, on_delete=models.CASCADE, related_name="network_policy")
    allowed_networks = models.JSONField(default=list, blank=True)
    trust_proxy_headers = models.BooleanField(default=False)
    enabled = models.BooleanField(default=False)
    allow_unpaid_kitchen = models.BooleanField(default=False)
    allow_untrusted_kitchen = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def allows(self, address):
        if not self.enabled or not self.allowed_networks:
            return True
        try:
            ip = ipaddress.ip_address(address)
            return any(ip in ipaddress.ip_network(network, strict=False) for network in self.allowed_networks)
        except (ValueError, TypeError):
            return False

    def allows_request(self, request):
        address = request.META.get("REMOTE_ADDR", "")
        if self.trust_proxy_headers:
            forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            address = forwarded or address
        return self.allows(address)


class SecurityAuditLog(models.Model):
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="security_audit_logs")
    event = models.CharField(max_length=100)
    actor = models.CharField(max_length=160, blank=True, default="")
    object_type = models.CharField(max_length=80, blank=True, default="")
    object_id = models.CharField(max_length=80, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def record(cls, business, event, *, actor="", object_type="", object_id="", metadata=None):
        return cls.objects.create(
            business=business, event=event, actor=actor, object_type=object_type,
            object_id=str(object_id), metadata=metadata or {},
        )


class Feature(models.Model):
    key = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")


class FeePlan(models.Model):
    name = models.CharField(max_length=120, unique=True)
    fixed_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    percentage = models.DecimalField(max_digits=7, decimal_places=4, default=Decimal("0.0000"))
    active = models.BooleanField(default=True)

    def calculate(self, amount):
        amount = Decimal(str(amount))
        return (self.fixed_fee + amount * self.percentage / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )


class BusinessFeature(models.Model):
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="features")
    feature = models.ForeignKey(Feature, on_delete=models.CASCADE)
    enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("business", "feature"), name="unique_business_feature")]


class BusinessFeePlan(models.Model):
    business = models.OneToOneField(BusinessProfile, on_delete=models.CASCADE, related_name="fee_plan")
    plan = models.ForeignKey(FeePlan, on_delete=models.PROTECT)


class PaymentIntent(models.Model):
    REQUIRES_PAYMENT_METHOD = "requires_payment_method"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    REFUNDED = "refunded"
    STATUS_CHOICES = tuple((value, value.replace("_", " ").title()) for value in (
        REQUIRES_PAYMENT_METHOD, REQUIRES_CONFIRMATION, PROCESSING, SUCCEEDED,
        FAILED, CANCELED, REFUNDED,
    ))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="payment_intents")
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payment_intents")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=REQUIRES_PAYMENT_METHOD)
    provider = models.CharField(max_length=64, default="local")
    provider_reference = models.CharField(max_length=160, blank=True, default="")
    idempotency_key = models.CharField(max_length=160)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("business", "idempotency_key"), name="unique_payment_idempotency"),
        ]
        ordering = ["-created_at"]


class PaymentWebhookEvent(models.Model):
    provider = models.CharField(max_length=64)
    event_id = models.CharField(max_length=160)
    event_type = models.CharField(max_length=80)
    payload = models.JSONField(default=dict)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("provider", "event_id"), name="unique_payment_webhook_event"),
        ]


class KitchenTicket(models.Model):
    QUEUED = "queued"
    PREPARING = "preparing"
    READY = "ready"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    STATUS_CHOICES = tuple((value, value.replace("_", " ").title()) for value in (
        QUEUED, PREPARING, READY, COMPLETED, CANCELLED,
    ))
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="kitchen_ticket")
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="kitchen_tickets")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=QUEUED)
    station = models.CharField(max_length=80, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_by = models.CharField(max_length=160, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]


class KitchenTicketItem(models.Model):
    PENDING = "pending"
    PREPARING = "preparing"
    READY = "ready"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    STATUS_CHOICES = tuple((value, value.replace("_", " ").title()) for value in (
        PENDING, PREPARING, READY, COMPLETED, CANCELLED,
    ))
    ticket = models.ForeignKey(KitchenTicket, on_delete=models.CASCADE, related_name="items")
    order_item = models.OneToOneField(OrderItem, on_delete=models.CASCADE, related_name="kitchen_ticket_item")
    station = models.CharField(max_length=80, blank=True, default="")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]


def calculate_fee(amount, *, fixed_fee=Decimal("0.00"), percentage=Decimal("0.00")):
    """Calculate a currency fee deterministically, rounded only at the end."""
    amount = Decimal(str(amount))
    return (Decimal(str(fixed_fee)) + amount * Decimal(str(percentage)) / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


__all__ = [
    "BusinessProfile", "MenuItem", "Order", "OrderItem", "RestaurantTable",
    "DiningSession", "RestaurantNetworkPolicy", "SecurityAuditLog", "Feature",
    "FeePlan", "BusinessFeature", "BusinessFeePlan", "PaymentIntent",
    "PaymentWebhookEvent", "calculate_fee",
    "KitchenTicket", "KitchenTicketItem",
]

# Restaurant operations foundation. These intentionally use simple quantities and
# signed movements so stock can be audited without a third-party inventory system.
class Outlet(models.Model):
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="outlets")
    name = models.CharField(max_length=120)
    code = models.SlugField(max_length=40)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["business", "code"], name="unique_outlet_code")]
    def __str__(self): return self.name

class StaffRole(models.Model):
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="staff_roles")
    name = models.CharField(max_length=80)
    permissions = models.JSONField(default=list)
    def allows(self, permission): return permission in self.permissions or "*" in self.permissions

class Ingredient(models.Model):
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="ingredients")
    name = models.CharField(max_length=120)
    sku = models.CharField(max_length=60, blank=True)
    unit = models.CharField(max_length=20, default="unit")
    stock_on_hand = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    reorder_level = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["business", "name"], name="unique_ingredient_name")]
    @property
    def is_low_stock(self): return self.stock_on_hand <= self.reorder_level

class Recipe(models.Model):
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="recipes")
    menu_item = models.OneToOneField(MenuItem, on_delete=models.CASCADE, related_name="recipe")
    yield_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    is_active = models.BooleanField(default=True)

class RecipeIngredient(models.Model):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="ingredients")
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT, related_name="recipe_lines")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["recipe", "ingredient"], name="unique_recipe_ingredient")]

class StockMovement(models.Model):
    PURCHASE = "purchase"; SALE = "sale"; WASTAGE = "wastage"; ADJUSTMENT = "adjustment"; TRANSFER = "transfer"
    REASONS = [(PURCHASE,"Purchase"),(SALE,"Sale"),(WASTAGE,"Wastage"),(ADJUSTMENT,"Adjustment"),(TRANSFER,"Transfer")]
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="stock_movements")
    outlet = models.ForeignKey(Outlet, null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_movements")
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT, related_name="movements")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    reason = models.CharField(max_length=20, choices=REASONS)
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_movements")
    idempotency_key = models.CharField(max_length=120, unique=True, null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class LowStockAlert(models.Model):
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="low_stock_alerts")
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE, related_name="alerts")
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["business", "ingredient"], condition=models.Q(acknowledged_at__isnull=True), name="one_open_low_stock_alert")]

class Supplier(models.Model):
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="suppliers")
    name = models.CharField(max_length=140)
    contact = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

class Purchase(models.Model):
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="purchases")
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name="purchases")
    outlet = models.ForeignKey(Outlet, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=20, default="received")
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    received_at = models.DateTimeField(auto_now_add=True)

class PurchaseLine(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="lines")
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)

class Wastage(models.Model):
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="wastage")
    outlet = models.ForeignKey(Outlet, null=True, blank=True, on_delete=models.SET_NULL)
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    reason = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

class Customer(models.Model):
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="customers")
    name = models.CharField(max_length=140, blank=True)
    phone = models.CharField(max_length=40)
    email = models.EmailField(blank=True)
    loyalty_points = models.PositiveIntegerField(default=0)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["business", "phone"], name="unique_customer_phone")]

class LoyaltyTransaction(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="loyalty_transactions")
    points = models.IntegerField()
    reason = models.CharField(max_length=120)
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

class Offer(models.Model):
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="offers")
    code = models.CharField(max_length=40)
    kind = models.CharField(max_length=20, choices=[("percent","Percent"),("fixed","Fixed"),("points","Points")])
    value = models.DecimalField(max_digits=10, decimal_places=2)
    active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True); ends_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["business", "code"], name="unique_offer_code")]

class FeeSettlement(models.Model):
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="fee_settlements")
    period_start = models.DateField(); period_end = models.DateField()
    gross_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    fee_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=20, default="pending")
    settled_at = models.DateTimeField(null=True, blank=True)

class OperationalReport(models.Model):
    business = models.ForeignKey(BusinessProfile, on_delete=models.CASCADE, related_name="operational_reports")
    report_date = models.DateField()
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["business", "report_date"], name="unique_operational_report_date")]
