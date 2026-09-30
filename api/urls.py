from django.urls import path

from . import views


urlpatterns = [
    path("health/", views.health, name="health"),
    path("models/", views.models, name="models"),
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
    path("orders/parse/", views.parse_order_text, name="parse-order-text"),
    path("conversations/", views.chat_conversations, name="chat-conversations"),
    path("conversations/<uuid:conversation_id>/", views.chat_conversation_detail, name="chat-conversation-detail"),
    path("memory/", views.chat_memory_preference, name="chat-memory-preference"),
    path("memories/", views.chat_memories, name="chat-memories"),
    path("memories/<int:memory_id>/", views.chat_memory_detail, name="chat-memory-detail"),
    path("chat/", views.chat, name="chat"),
    path("markdown/", views.render_markdown, name="render-markdown"),
]
