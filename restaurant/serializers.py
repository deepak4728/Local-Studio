"""Serializers used by the restaurant API."""
from api.serializers import (
    BusinessCatalogItemSerializer, BusinessProfileSerializer, BusinessSetupPromptSerializer,
    BusinessSetupSerializer, MenuItemCreateSerializer, MenuItemSerializer, OrderCreateSerializer,
    OrderItemCreateSerializer, OrderItemSerializer, OrderParseSerializer, OrderPreviewSerializer,
    OrderQueueFilterSerializer, OrderSerializer, OrderStatusUpdateSerializer, ParsedOrderResponseSerializer,
)
from rest_framework import serializers

from .models import (
    DiningSession, FeePlan, KitchenTicket, KitchenTicketItem, PaymentIntent,
    RestaurantNetworkPolicy, RestaurantTable,
)


class RestaurantTableSerializer(serializers.ModelSerializer):
    qr_token = serializers.SerializerMethodField()

    class Meta:
        model = RestaurantTable
        fields = ("id", "name", "is_active", "qr_token", "created_at")
        read_only_fields = ("id", "created_at")

    def get_qr_token(self, obj):
        return obj.sign()


class DiningSessionSerializer(serializers.ModelSerializer):
    token = serializers.SerializerMethodField()

    class Meta:
        model = DiningSession
        fields = ("id", "table", "expires_at", "token", "created_at")
        read_only_fields = ("id", "token", "created_at")

    def get_token(self, obj):
        return obj.sign()


class RestaurantNetworkPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = RestaurantNetworkPolicy
        fields = (
            "allowed_networks", "trust_proxy_headers", "enabled",
            "allow_unpaid_kitchen", "allow_untrusted_kitchen", "updated_at",
        )
        read_only_fields = ("updated_at",)


class FeePlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeePlan
        fields = ("id", "name", "fixed_fee", "percentage", "active")


class PaymentIntentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentIntent
        fields = (
            "id", "order", "amount", "currency", "status", "provider",
            "provider_reference", "idempotency_key", "metadata", "created_at",
        )
        read_only_fields = (
            "id", "amount", "status", "provider_reference", "created_at",
        )


class PaymentIntentCreateSerializer(serializers.Serializer):
    order_id = serializers.IntegerField(min_value=1)
    idempotency_key = serializers.CharField(max_length=160)
    provider = serializers.CharField(max_length=64, required=False, default="local")


class KitchenTicketItemSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="order_item.menu_item.name", read_only=True)
    quantity = serializers.IntegerField(source="order_item.quantity", read_only=True)

    class Meta:
        model = KitchenTicketItem
        fields = ("id", "order_item", "name", "quantity", "station", "status",
                  "started_at", "ready_at", "completed_at")
        read_only_fields = ("id", "order_item", "name", "quantity", "started_at", "ready_at", "completed_at")


class KitchenTicketSerializer(serializers.ModelSerializer):
    items = KitchenTicketItemSerializer(many=True, read_only=True)
    order_id = serializers.IntegerField(read_only=True)
    order_customer_name = serializers.CharField(source="order.customer_name", read_only=True)

    class Meta:
        model = KitchenTicket
        fields = ("id", "order_id", "order_customer_name", "status", "station", "notes",
                  "created_by", "created_at", "started_at", "ready_at", "completed_at", "items")
        read_only_fields = (
            "id", "order_id", "order_customer_name", "created_by", "created_at",
            "started_at", "ready_at", "completed_at", "items",
        )


class KitchenTicketCreateSerializer(serializers.Serializer):
    station = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class KitchenStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=tuple(value for value, _ in KitchenTicket.STATUS_CHOICES))
    station = serializers.CharField(max_length=80, required=False, allow_blank=True)


class KitchenItemStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=tuple(value for value, _ in KitchenTicketItem.STATUS_CHOICES))
    station = serializers.CharField(max_length=80, required=False, allow_blank=True)

__all__ = [name for name in globals() if name.endswith("Serializer")]

from .models import (Outlet, Ingredient, Recipe, RecipeIngredient, StockMovement, LowStockAlert,
    Supplier, Purchase, PurchaseLine, Wastage, Customer, LoyaltyTransaction, Offer, FeeSettlement, OperationalReport)

class OperationsModelSerializer(serializers.ModelSerializer):
    class Meta:
        fields = "__all__"

for _name, _model in [("Outlet",Outlet),("Ingredient",Ingredient),("Recipe",Recipe),("RecipeIngredient",RecipeIngredient),
    ("StockMovement",StockMovement),("LowStockAlert",LowStockAlert),("Supplier",Supplier),("Purchase",Purchase),
    ("PurchaseLine",PurchaseLine),("Wastage",Wastage),("Customer",Customer),("LoyaltyTransaction",LoyaltyTransaction),
    ("Offer",Offer),("FeeSettlement",FeeSettlement),("OperationalReport",OperationalReport)]:
    globals()[f"{_name}Serializer"] = type(f"{_name}Serializer", (OperationsModelSerializer,), {"Meta": type("Meta", (), {"model": _model, "fields": "__all__", "read_only_fields": ("business", "created_at", "received_at")})})
