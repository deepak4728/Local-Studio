from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from api.models import BusinessProfile, MenuItem, Order, OrderItem
from .models import (
    KitchenTicket, KitchenTicketItem, PaymentIntent, PaymentWebhookEvent,
    RestaurantNetworkPolicy, SecurityAuditLog,
)
from .payments import apply_webhook, create_intent


class PaymentTests(TestCase):
    def setUp(self):
        self.business = BusinessProfile.get_or_create_default()
        item = MenuItem.objects.create(name="Soup", price="5.00")
        self.order = Order.objects.create(business=self.business)
        OrderItem.objects.create(order=self.order, menu_item=item, unit_price="5.00")
        self.order.recalculate_totals()

    def test_local_adapter_is_deterministic_and_idempotent(self):
        first = create_intent(
            business=self.business, order=self.order, idempotency_key="same-key"
        )
        second = create_intent(
            business=self.business, order=self.order, idempotency_key="same-key"
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.status, PaymentIntent.REQUIRES_CONFIRMATION)
        self.assertEqual(first.provider_reference, f"local_{first.id}")

    def test_webhook_is_idempotent_and_rejects_invalid_refund(self):
        intent = create_intent(
            business=self.business, order=self.order, idempotency_key="webhook-key"
        )
        apply_webhook(
            provider="local", event_id="evt-1", event_type="payment.succeeded",
            intent_id=intent.pk, status=PaymentIntent.SUCCEEDED,
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, Order.PAYMENT_PAID)
        apply_webhook(
            provider="local", event_id="evt-1", event_type="payment.succeeded",
            intent_id=intent.pk, status=PaymentIntent.SUCCEEDED,
        )
        self.assertEqual(PaymentWebhookEvent.objects.count(), 1)
        with self.assertRaises(ValueError):
            apply_webhook(
                provider="local", event_id="evt-2", event_type="payment.refunded",
                intent_id=intent.pk, status=PaymentIntent.CANCELED,
            )

    def test_webhook_endpoint_requires_no_api_key_but_is_deduplicated(self):
        client = APIClient()
        intent = create_intent(
            business=self.business, order=self.order, idempotency_key="http-key"
        )
        payload = {
            "provider": "local", "event_id": "http-evt", "intent_id": str(intent.pk),
            "status": PaymentIntent.SUCCEEDED,
        }
        response = client.post("/api/restaurant/payments/webhook/", payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.post("/api/restaurant/payments/webhook/", payload, format="json").status_code, 200)


@override_settings(STAFF_API_KEY="test-staff")
class KitchenWorkflowTests(TestCase):
    def setUp(self):
        self.business = BusinessProfile.get_or_create_default()
        item = MenuItem.objects.create(name="Soup", price="5.00")
        self.order = Order.objects.create(business=self.business, payment_status=Order.PAYMENT_PAID)
        OrderItem.objects.create(order=self.order, menu_item=item, unit_price="5.00")
        self.order.recalculate_totals()
        self.client = APIClient()
        self.client.defaults["HTTP_X_STAFF_KEY"] = "test-staff"

    def approve(self):
        response = self.client.patch(
            f"/api/restaurant/orders/{self.order.pk}/review/",
            {"review_status": Order.REVIEW_APPROVED, "review_note": "Menu verified"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_review_gate_and_ticket_creation(self):
        response = self.client.post(
            "/api/restaurant/kitchen/tickets/",
            {"order_id": self.order.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.approve()
        response = self.client.post(
            "/api/restaurant/kitchen/tickets/",
            {"order_id": self.order.pk, "station": "grill"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(KitchenTicket.objects.count(), 1)
        self.assertEqual(KitchenTicketItem.objects.count(), 1)
        self.assertTrue(SecurityAuditLog.objects.filter(event="kitchen.ticket_created").exists())

    def test_unpaid_ticket_requires_policy_and_transitions_are_audited(self):
        self.order.payment_status = Order.PAYMENT_PENDING
        self.order.save(update_fields=["payment_status"])
        self.approve()
        denied = self.client.post(
            "/api/restaurant/kitchen/tickets/", {"order_id": self.order.pk}, format="json"
        )
        self.assertEqual(denied.status_code, 402)
        policy = RestaurantNetworkPolicy.objects.create(
            business=self.business, allow_unpaid_kitchen=True
        )
        created = self.client.post(
            "/api/restaurant/kitchen/tickets/", {"order_id": self.order.pk}, format="json"
        )
        self.assertEqual(created.status_code, 201)
        ticket_id = created.data["id"]
        for status in (KitchenTicket.PREPARING, KitchenTicket.READY, KitchenTicket.COMPLETED):
            response = self.client.patch(
                f"/api/restaurant/kitchen/tickets/{ticket_id}/status/",
                {"status": status}, format="json",
            )
            self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.fulfillment_status, Order.STATUS_COMPLETED)
        self.assertGreaterEqual(SecurityAuditLog.objects.filter(event="kitchen.ticket_transition").count(), 3)

    def test_invalid_ticket_transition_is_rejected(self):
        self.approve()
        response = self.client.post(
            "/api/restaurant/kitchen/tickets/", {"order_id": self.order.pk}, format="json"
        )
        ticket_id = response.data["id"]
        response = self.client.patch(
            f"/api/restaurant/kitchen/tickets/{ticket_id}/status/",
            {"status": KitchenTicket.READY}, format="json",
        )
        self.assertEqual(response.status_code, 409)
