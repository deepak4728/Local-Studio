"""Restaurant HTTP handlers extracted from the legacy API module."""
from api.views import (
    business_profile, business_setup, business_setup_draft, customer_order_page,
    menu_items, order_detail, order_queue, order_status, orders, parse_order_text,
    preview_order, staff_dashboard, staff_dashboard_page, staff_menu_page,
    staff_kitchen_page, staff_settings_page,
)
from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.decorators import authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from api.models import BusinessProfile
from api.serializers import OrderSerializer
from api.authentication import StaffKeyAuthentication
from api.models import Order
from .models import (
    DiningSession, KitchenTicket, KitchenTicketItem, PaymentIntent,
    RestaurantNetworkPolicy, RestaurantTable, SecurityAuditLog,
)
from .payments import apply_webhook, create_intent, get_adapter, transition
from .serializers import (
    DiningSessionSerializer, PaymentIntentCreateSerializer, PaymentIntentSerializer,
    RestaurantNetworkPolicySerializer, RestaurantTableSerializer,
    KitchenItemStatusSerializer, KitchenStatusSerializer, KitchenTicketCreateSerializer,
    KitchenTicketSerializer,
)


@api_view(["GET", "POST"])
@authentication_classes([StaffKeyAuthentication])
@permission_classes([IsAuthenticated])
def restaurant_tables(request):
    business = BusinessProfile.get_or_create_default()
    if request.method == "GET":
        return Response(RestaurantTableSerializer(
            RestaurantTable.objects.filter(business=business), many=True
        ).data)
    serializer = RestaurantTableSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return Response(
        RestaurantTableSerializer(serializer.save(business=business)).data,
        status=201,
    )


@api_view(["POST"])
def restaurant_table_session(request, table_id):
    business = BusinessProfile.get_or_create_default()
    table = get_object_or_404(RestaurantTable, pk=table_id, business=business, is_active=True)
    # A session can only be minted from the signed QR payload for this table.
    signed_table = request.data.get("table_token")
    if not signed_table:
        return Response({"detail": "A signed table token is required."}, status=400)
    try:
        if RestaurantTable.verify(signed_table).pk != table.pk:
            raise ValueError
    except Exception:
        return Response({"detail": "Invalid table token."}, status=400)
    try:
        minutes = max(1, min(int(request.data.get("minutes", 120)), 24 * 60))
    except (TypeError, ValueError):
        minutes = 120
    session = DiningSession.objects.create(
        table=table, expires_at=timezone.now() + timedelta(minutes=minutes)
    )
    return Response(DiningSessionSerializer(session).data, status=201)


@api_view(["GET", "PATCH"])
@authentication_classes([StaffKeyAuthentication])
@permission_classes([IsAuthenticated])
def restaurant_network_policy(request):
    business = BusinessProfile.get_or_create_default()
    policy, _ = RestaurantNetworkPolicy.objects.get_or_create(business=business)
    if request.method == "GET":
        return Response(RestaurantNetworkPolicySerializer(policy).data)
    serializer = RestaurantNetworkPolicySerializer(policy, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    return Response(RestaurantNetworkPolicySerializer(serializer.save()).data)


@api_view(["POST"])
@authentication_classes([StaffKeyAuthentication])
@permission_classes([IsAuthenticated])
def payment_intents(request):
    serializer = PaymentIntentCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    business = BusinessProfile.get_or_create_default()
    order = get_object_or_404(Order, pk=serializer.validated_data["order_id"], business=business)
    intent = create_intent(
        business=business,
        order=order,
        idempotency_key=serializer.validated_data["idempotency_key"],
        provider=serializer.validated_data["provider"],
    )
    return Response(PaymentIntentSerializer(intent).data, status=201)


@api_view(["GET", "POST"])
@authentication_classes([StaffKeyAuthentication])
@permission_classes([IsAuthenticated])
def payment_intent_detail(request, intent_id):
    business = BusinessProfile.get_or_create_default()
    intent = get_object_or_404(PaymentIntent, pk=intent_id, business=business)
    if request.method == "POST":
        action = request.data.get("action", "confirm")
        if action == "refund":
            result = get_adapter(intent.provider).refund(intent)
        elif action == "cancel":
            result = type("Result", (), {"status": PaymentIntent.CANCELED})()
        else:
            result = get_adapter(intent.provider).confirm(intent)
        transition(intent, result.status)
        if getattr(result, "reference", None) and not intent.provider_reference:
            intent.provider_reference = result.reference
            intent.save(update_fields=["provider_reference", "updated_at"])
    return Response(PaymentIntentSerializer(intent).data)


@api_view(["POST"])
@permission_classes([])
@authentication_classes([])
def payment_webhook(request):
    payload = request.data
    try:
        intent = apply_webhook(
            provider=str(payload["provider"]),
            event_id=str(payload["event_id"]),
            event_type=str(payload.get("type", "payment.updated")),
            intent_id=payload["intent_id"],
            status=str(payload["status"]),
            payload=payload,
        )
    except (KeyError, ValueError, PaymentIntent.DoesNotExist):
        return Response({"detail": "Invalid payment event."}, status=400)
    return Response(PaymentIntentSerializer(intent).data)


def _staff_actor(request):
    if getattr(getattr(request, "auth", None), "is_staff", False):
        return "staff-key"
    return str(getattr(request, "user", ""))[:160]


def _kitchen_access(order, request):
    """Return an actionable denial for orders that are not safe to prepare."""
    policy = RestaurantNetworkPolicy.objects.filter(business=order.business).first()
    trusted = bool(getattr(getattr(request, "auth", None), "is_staff", False))
    if not trusted:
        from .payments import request_is_trusted
        trusted = request_is_trusted(request, order.business)
    if not trusted and not (policy and policy.allow_untrusted_kitchen):
        return "A trusted staff, dining-session, or restaurant-network request is required."
    if order.payment_status != Order.PAYMENT_PAID and not (policy and policy.allow_unpaid_kitchen):
        return "Payment is required before this order can enter the kitchen."
    if order.review_status != Order.REVIEW_APPROVED:
        return "A staff review approval is required before this order can enter the kitchen."
    return None


@api_view(["PATCH"])
@authentication_classes([StaffKeyAuthentication])
@permission_classes([IsAuthenticated])
def order_review(request, order_id):
    business = BusinessProfile.get_or_create_default()
    order = get_object_or_404(Order, pk=order_id, business=business)
    decision = request.data.get("review_status")
    if decision not in (Order.REVIEW_APPROVED, Order.REVIEW_REJECTED):
        return Response({"detail": "review_status must be approved or rejected."}, status=400)
    before = order.review_status
    order.review_status = decision
    order.review_note = str(request.data.get("review_note", ""))[:10000]
    order.reviewed_by = _staff_actor(request)
    order.reviewed_at = timezone.now()
    order.save(update_fields=["review_status", "review_note", "reviewed_by", "reviewed_at", "updated_at"])
    SecurityAuditLog.record(
        business, "order.reviewed", actor=order.reviewed_by, object_type="order",
        object_id=order.pk, metadata={"before": before, "after": decision, "note": order.review_note},
    )
    return Response({"order": OrderSerializer(order).data})


@api_view(["GET", "POST"])
@authentication_classes([StaffKeyAuthentication])
@permission_classes([IsAuthenticated])
def kitchen_tickets(request):
    business = BusinessProfile.get_or_create_default()
    if request.method == "GET":
        tickets = KitchenTicket.objects.filter(business=business).select_related(
            "order"
        ).prefetch_related("items__order_item__menu_item")
        status_filter = request.query_params.get("status")
        if status_filter:
            tickets = tickets.filter(status=status_filter)
        return Response(KitchenTicketSerializer(tickets, many=True).data)

    order_id = request.data.get("order_id")
    order = get_object_or_404(Order, pk=order_id, business=business)
    denial = _kitchen_access(order, request)
    if denial:
        return Response({"detail": denial}, status=402 if order.payment_status != Order.PAYMENT_PAID else 403)
    if hasattr(order, "kitchen_ticket"):
        return Response(KitchenTicketSerializer(order.kitchen_ticket).data, status=200)
    payload = KitchenTicketCreateSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    with transaction.atomic():
        ticket = KitchenTicket.objects.create(
            business=business, order=order, station=payload.validated_data["station"],
            notes=payload.validated_data["notes"], created_by=_staff_actor(request),
        )
        for item in order.items.select_related("menu_item").all():
            KitchenTicketItem.objects.create(
                ticket=ticket, order_item=item, station=payload.validated_data["station"]
            )
        order.fulfillment_status = Order.STATUS_CONFIRMED
        order.status = Order.STATUS_CONFIRMED
        order.save(update_fields=["fulfillment_status", "status", "updated_at"])
        SecurityAuditLog.record(
            business, "kitchen.ticket_created", actor=ticket.created_by,
            object_type="kitchen_ticket", object_id=ticket.pk, metadata={"order_id": order.pk},
        )
    return Response(KitchenTicketSerializer(ticket).data, status=201)


@api_view(["PATCH"])
@authentication_classes([StaffKeyAuthentication])
@permission_classes([IsAuthenticated])
def kitchen_ticket_status(request, ticket_id):
    business = BusinessProfile.get_or_create_default()
    ticket = get_object_or_404(KitchenTicket.objects.select_related("order"), pk=ticket_id, business=business)
    payload = KitchenStatusSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    new_status = payload.validated_data["status"]
    allowed = {
        KitchenTicket.QUEUED: {KitchenTicket.QUEUED, KitchenTicket.PREPARING, KitchenTicket.CANCELLED},
        KitchenTicket.PREPARING: {KitchenTicket.PREPARING, KitchenTicket.READY, KitchenTicket.CANCELLED},
        KitchenTicket.READY: {KitchenTicket.READY, KitchenTicket.COMPLETED},
        KitchenTicket.COMPLETED: {KitchenTicket.COMPLETED},
        KitchenTicket.CANCELLED: {KitchenTicket.CANCELLED},
    }
    if new_status not in allowed[ticket.status]:
        return Response({"detail": f"Invalid kitchen transition: {ticket.status} -> {new_status}"}, status=409)
    now = timezone.now()
    ticket.status = new_status
    if "station" in payload.validated_data:
        ticket.station = payload.validated_data["station"]
    if new_status == KitchenTicket.PREPARING and ticket.started_at is None:
        ticket.started_at = now
        ticket.order.fulfillment_status = Order.STATUS_PREPARING
    elif new_status == KitchenTicket.READY:
        ticket.ready_at = now
        ticket.order.fulfillment_status = Order.STATUS_READY
    elif new_status == KitchenTicket.COMPLETED:
        ticket.completed_at = now
        ticket.order.fulfillment_status = Order.STATUS_COMPLETED
    elif new_status == KitchenTicket.CANCELLED:
        ticket.order.fulfillment_status = Order.STATUS_CANCELLED
    ticket.order.status = ticket.order.fulfillment_status
    ticket.order.save(update_fields=["status", "fulfillment_status", "updated_at"])
    ticket.save(update_fields=["status", "station", "started_at", "ready_at", "completed_at"])
    if new_status == KitchenTicket.COMPLETED:
        deduct_order_inventory(ticket.order, _staff_actor(request))
    SecurityAuditLog.record(
        business, "kitchen.ticket_transition", actor=_staff_actor(request),
        object_type="kitchen_ticket", object_id=ticket.pk,
        metadata={"status": new_status, "order_id": ticket.order_id},
    )
    return Response(KitchenTicketSerializer(ticket).data)


@api_view(["PATCH"])
@authentication_classes([StaffKeyAuthentication])
@permission_classes([IsAuthenticated])
def kitchen_item_status(request, item_id):
    business = BusinessProfile.get_or_create_default()
    item = get_object_or_404(
        KitchenTicketItem.objects.select_related("ticket__order", "order_item__menu_item"),
        pk=item_id, ticket__business=business,
    )
    payload = KitchenItemStatusSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    new_status = payload.validated_data["status"]
    allowed = {
        KitchenTicketItem.PENDING: {KitchenTicketItem.PENDING, KitchenTicketItem.PREPARING, KitchenTicketItem.CANCELLED},
        KitchenTicketItem.PREPARING: {KitchenTicketItem.PREPARING, KitchenTicketItem.READY, KitchenTicketItem.CANCELLED},
        KitchenTicketItem.READY: {KitchenTicketItem.READY, KitchenTicketItem.COMPLETED},
        KitchenTicketItem.COMPLETED: {KitchenTicketItem.COMPLETED},
        KitchenTicketItem.CANCELLED: {KitchenTicketItem.CANCELLED},
    }
    if new_status not in allowed[item.status]:
        return Response({"detail": f"Invalid item transition: {item.status} -> {new_status}"}, status=409)
    now = timezone.now()
    item.status = new_status
    if "station" in payload.validated_data:
        item.station = payload.validated_data["station"]
    if new_status == KitchenTicketItem.PREPARING and item.started_at is None:
        item.started_at = now
    elif new_status == KitchenTicketItem.READY:
        item.ready_at = now
    elif new_status == KitchenTicketItem.COMPLETED:
        item.completed_at = now
    item.save(update_fields=["status", "station", "started_at", "ready_at", "completed_at"])
    sibling_statuses = set(
        item.ticket.items.values_list("status", flat=True)
    )
    if sibling_statuses and sibling_statuses <= {KitchenTicketItem.COMPLETED}:
        item.ticket.status = KitchenTicket.COMPLETED
        item.ticket.completed_at = now
        item.ticket.order.fulfillment_status = Order.STATUS_COMPLETED
        item.ticket.order.status = Order.STATUS_COMPLETED
        item.ticket.save(update_fields=["status", "completed_at"])
        item.ticket.order.save(update_fields=["status", "fulfillment_status", "updated_at"])
        deduct_order_inventory(item.ticket.order, _staff_actor(request))
    elif sibling_statuses and sibling_statuses <= {KitchenTicketItem.READY, KitchenTicketItem.COMPLETED}:
        item.ticket.status = KitchenTicket.READY
        item.ticket.ready_at = now
        item.ticket.order.fulfillment_status = Order.STATUS_READY
        item.ticket.order.status = Order.STATUS_READY
        item.ticket.save(update_fields=["status", "ready_at"])
        item.ticket.order.save(update_fields=["status", "fulfillment_status", "updated_at"])
    SecurityAuditLog.record(
        business, "kitchen.item_transition", actor=_staff_actor(request),
        object_type="kitchen_ticket_item", object_id=item.pk,
        metadata={"status": new_status, "ticket_id": item.ticket_id},
    )
    return Response(KitchenTicketItemSerializer(item).data)

__all__ = [
    "business_profile", "business_setup", "business_setup_draft", "customer_order_page",
    "menu_items", "order_detail", "order_queue", "order_status", "orders",
    "parse_order_text", "preview_order", "staff_dashboard", "staff_dashboard_page",
    "staff_menu_page", "staff_kitchen_page", "staff_settings_page", "restaurant_tables",
    "restaurant_table_session", "restaurant_network_policy",
    "payment_intents", "payment_intent_detail", "payment_webhook",
    "order_review", "kitchen_tickets", "kitchen_ticket_status", "kitchen_item_status",
]

# Operations API: intentionally boring CRUD keeps staff tooling compatible with
# browser clients while all stock-changing writes remain transactional.
from django.db.models import Sum, Count, F
from .operations import deduct_order_inventory, receive_purchase, record_wastage
from .models import (Outlet, Ingredient, Recipe, RecipeIngredient, StockMovement, LowStockAlert,
    Supplier, Purchase, PurchaseLine, Wastage, Customer, LoyaltyTransaction, Offer, FeeSettlement, OperationalReport)
from .serializers import (OutletSerializer, IngredientSerializer, RecipeSerializer, RecipeIngredientSerializer,
    StockMovementSerializer, LowStockAlertSerializer, SupplierSerializer, PurchaseSerializer, PurchaseLineSerializer,
    WastageSerializer, CustomerSerializer, LoyaltyTransactionSerializer, OfferSerializer, FeeSettlementSerializer,
    OperationalReportSerializer)

_OPERATION_MODELS = {
    "outlets": (Outlet, OutletSerializer), "ingredients": (Ingredient, IngredientSerializer),
    "recipes": (Recipe, RecipeSerializer), "recipe-ingredients": (RecipeIngredient, RecipeIngredientSerializer),
    "stock-movements": (StockMovement, StockMovementSerializer), "low-stock-alerts": (LowStockAlert, LowStockAlertSerializer),
    "suppliers": (Supplier, SupplierSerializer), "purchases": (Purchase, PurchaseSerializer),
    "purchase-lines": (PurchaseLine, PurchaseLineSerializer), "wastage": (Wastage, WastageSerializer),
    "customers": (Customer, CustomerSerializer), "loyalty": (LoyaltyTransaction, LoyaltyTransactionSerializer),
    "offers": (Offer, OfferSerializer), "fee-settlements": (FeeSettlement, FeeSettlementSerializer),
    "reports": (OperationalReport, OperationalReportSerializer),
}

@api_view(["GET", "POST"])
@authentication_classes([StaffKeyAuthentication])
@permission_classes([IsAuthenticated])
def operations_collection(request, resource):
    if resource not in _OPERATION_MODELS: return Response({"detail": "Unknown resource."}, status=404)
    model, serializer = _OPERATION_MODELS[resource]; business = BusinessProfile.get_or_create_default()
    qs = model.objects.filter(business=business) if any(f.name == "business" for f in model._meta.fields) else model.objects.filter(
        **({"purchase__business": business} if model is PurchaseLine else {"customer__business": business} if model is LoyaltyTransaction else {"recipe__business": business} if model is RecipeIngredient else {"ingredient__business": business}))
    if request.method == "GET":
        if resource == "low-stock-alerts": qs = qs.filter(acknowledged_at__isnull=True)
        return Response(serializer(qs.order_by("-pk"), many=True).data)
    payload = serializer(data=request.data); payload.is_valid(raise_exception=True)
    obj = payload.save(business=business) if any(f.name == "business" for f in model._meta.fields) else payload.save()
    if resource == "purchases": obj.save()
    if resource == "wastage": record_wastage(obj, _staff_actor(request))
    if resource == "purchases" and obj.status == "received": receive_purchase(obj, _staff_actor(request))
    return Response(serializer(obj).data, status=201)

@api_view(["GET"])
@authentication_classes([StaffKeyAuthentication])
@permission_classes([IsAuthenticated])
def operations_report(request):
    business = BusinessProfile.get_or_create_default()
    return Response({"orders": Order.objects.filter(business=business).count(),
        "revenue": str(Order.objects.filter(business=business).aggregate(v=Sum("total"))["v"] or 0),
        "low_stock": Ingredient.objects.filter(business=business, stock_on_hand__lte=F("reorder_level")).count(),
        "wastage": str(Wastage.objects.filter(business=business).aggregate(v=Sum("quantity"))["v"] or 0)})
