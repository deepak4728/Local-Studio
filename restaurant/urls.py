from django.urls import path

from . import views

urlpatterns = [
    path("business/profile/", views.business_profile, name="business-profile"),
    path("business/draft/", views.business_setup_draft, name="business-setup-draft"),
    path("business/setup/", views.business_setup, name="business-setup"),
    path("menu/", views.menu_items, name="menu-items"),
    path("staff/dashboard/", views.staff_dashboard, name="staff-dashboard"),
    path("orders/preview/", views.preview_order, name="preview-order"),
    path("orders/queue/", views.order_queue, name="order-queue"),
    path("orders/", views.orders, name="orders"),
    path("orders/<int:order_id>/", views.order_detail, name="order-detail"),
    path("orders/<int:order_id>/status/", views.order_status, name="order-status"),
    path("orders/<int:order_id>/review/", views.order_review, name="order-review"),
    path("kitchen/tickets/", views.kitchen_tickets, name="kitchen-tickets"),
    path("kitchen/tickets/<int:ticket_id>/status/", views.kitchen_ticket_status, name="kitchen-ticket-status"),
    path("kitchen/items/<int:item_id>/status/", views.kitchen_item_status, name="kitchen-item-status"),
    path("orders/parse/", views.parse_order_text, name="parse-order-text"),
    path("orders/ai-draft/", views.parse_order_text, name="ai-order-draft"),
    path("tables/", views.restaurant_tables, name="restaurant-tables"),
    path("tables/<int:table_id>/sessions/", views.restaurant_table_session, name="restaurant-table-session"),
    path("network-policy/", views.restaurant_network_policy, name="restaurant-network-policy"),
    path("payments/intents/", views.payment_intents, name="payment-intents"),
    path("payments/intents/<uuid:intent_id>/", views.payment_intent_detail, name="payment-intent-detail"),
    path("payments/webhook/", views.payment_webhook, name="payment-webhook"),
    path("operations/report/", views.operations_report, name="operations-report"),
    path("operations/<str:resource>/", views.operations_collection, name="operations-collection"),
]
