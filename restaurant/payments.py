"""Provider-neutral payment boundary and deterministic local adapter."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from django.db import transaction
from django.utils import timezone

from .models import PaymentIntent, PaymentWebhookEvent
from .models import RestaurantNetworkPolicy


@dataclass(frozen=True)
class PaymentResult:
    reference: str
    status: str


class PaymentAdapter(Protocol):
    name: str
    def create(self, intent: PaymentIntent) -> PaymentResult: ...
    def confirm(self, intent: PaymentIntent) -> PaymentResult: ...
    def refund(self, intent: PaymentIntent) -> PaymentResult: ...


class LocalPaymentAdapter:
    """No-network adapter: references and outcomes are derived from the intent."""
    name = "local"

    def create(self, intent):
        return PaymentResult(f"local_{intent.id}", PaymentIntent.REQUIRES_CONFIRMATION)

    def confirm(self, intent):
        return PaymentResult(intent.provider_reference or f"local_{intent.id}", PaymentIntent.SUCCEEDED)

    def refund(self, intent):
        return PaymentResult(intent.provider_reference, PaymentIntent.REFUNDED)


ADAPTERS = {"local": LocalPaymentAdapter()}


def get_adapter(name="local"):
    try:
        return ADAPTERS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown payment provider: {name}") from exc


def request_is_trusted(request, business):
    """Trust a live signed dining session or an allowed restaurant network."""
    token = request.data.get("session_token") or request.headers.get("X-Dining-Session")
    if token:
        try:
            from .models import DiningSession
            session = DiningSession.verify(token)
            if session.table.business_id == business.pk:
                return True
        except Exception:
            pass
    policy = RestaurantNetworkPolicy.objects.filter(business=business).first()
    return policy is None or policy.allows_request(request)


ALLOWED_TRANSITIONS = {
    PaymentIntent.REQUIRES_PAYMENT_METHOD: {
        PaymentIntent.REQUIRES_PAYMENT_METHOD, PaymentIntent.REQUIRES_CONFIRMATION,
        PaymentIntent.CANCELED,
    },
    PaymentIntent.REQUIRES_CONFIRMATION: {
        PaymentIntent.REQUIRES_CONFIRMATION, PaymentIntent.PROCESSING,
        PaymentIntent.SUCCEEDED, PaymentIntent.FAILED, PaymentIntent.CANCELED,
    },
    PaymentIntent.PROCESSING: {
        PaymentIntent.PROCESSING, PaymentIntent.SUCCEEDED, PaymentIntent.FAILED,
        PaymentIntent.CANCELED,
    },
    PaymentIntent.SUCCEEDED: {PaymentIntent.SUCCEEDED, PaymentIntent.REFUNDED},
    PaymentIntent.FAILED: {PaymentIntent.FAILED, PaymentIntent.REQUIRES_PAYMENT_METHOD},
    PaymentIntent.CANCELED: {PaymentIntent.CANCELED},
    PaymentIntent.REFUNDED: {PaymentIntent.REFUNDED},
}


def transition(intent, new_status):
    if new_status not in ALLOWED_TRANSITIONS[intent.status]:
        raise ValueError(f"Invalid payment transition: {intent.status} -> {new_status}")
    if intent.status != new_status:
        intent.status = new_status
        intent.save(update_fields=["status", "updated_at"])
    if new_status == PaymentIntent.SUCCEEDED:
        intent.order.payment_status = intent.order.PAYMENT_PAID
        intent.order.save(update_fields=["payment_status", "updated_at"])
    elif new_status == PaymentIntent.REFUNDED:
        intent.order.payment_status = intent.order.PAYMENT_REFUNDED
        intent.order.save(update_fields=["payment_status", "updated_at"])
    elif new_status == PaymentIntent.FAILED:
        intent.order.payment_status = intent.order.PAYMENT_FAILED
        intent.order.save(update_fields=["payment_status", "updated_at"])
    return intent


@transaction.atomic
def apply_webhook(*, provider, event_id, event_type, intent_id, status, payload=None):
    event, created = PaymentWebhookEvent.objects.get_or_create(
        provider=provider, event_id=event_id,
        defaults={"event_type": event_type, "payload": payload or {}},
    )
    if not created and event.processed_at:
        original_intent_id = event.payload.get("intent_id", intent_id)
        return PaymentIntent.objects.get(pk=original_intent_id)
    intent = PaymentIntent.objects.select_for_update().get(pk=intent_id)
    transition(intent, status)
    event.processed_at = timezone.now()
    event.save(update_fields=["processed_at"])
    return intent


def create_intent(*, business, order, idempotency_key, provider="local"):
    existing = PaymentIntent.objects.filter(
        business=business, idempotency_key=idempotency_key
    ).first()
    if existing:
        return existing
    adapter = get_adapter(provider)
    intent = PaymentIntent.objects.create(
        business=business, order=order, amount=Decimal(order.total),
        provider=provider, idempotency_key=idempotency_key,
    )
    result = adapter.create(intent)
    intent.provider_reference = result.reference
    transition(intent, result.status)
    return intent
