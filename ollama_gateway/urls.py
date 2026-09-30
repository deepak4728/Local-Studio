from django.urls import include, path

from api.views import chat_interface, customer_order_page, staff_dashboard_page, staff_menu_page, staff_settings_page


urlpatterns = [
    path("", chat_interface, name="chat-interface"),
    path("staff/", staff_dashboard_page, name="staff-dashboard-page"),
    path("staff/menu/", staff_menu_page, name="staff-menu-page"),
    path("staff/settings/", staff_settings_page, name="staff-settings-page"),
    path("order/", customer_order_page, name="customer-order-page"),
    path("api/", include("api.urls")),
]
