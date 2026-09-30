from django.urls import include, path

from api.views import (
    customer_order_page, restaurant_home_page, staff_dashboard_page,
    staff_kitchen_page, staff_menu_page, staff_settings_page,
)
from chat.views import chat_interface


restaurant_browser_urls = [
    path("", restaurant_home_page, name="restaurant-home-page"),
    path("order/", customer_order_page, name="restaurant-order-page"),
    path("staff/", staff_dashboard_page, name="restaurant-staff-dashboard-page"),
    path("staff/kitchen/", staff_kitchen_page, name="restaurant-staff-kitchen-page"),
    path("staff/menu/", staff_menu_page, name="restaurant-staff-menu-page"),
    path("staff/settings/", staff_settings_page, name="restaurant-staff-settings-page"),
]

urlpatterns = [
    path("", chat_interface, name="chat-interface"),
    path("chat/", include("chat.urls")),
    path("restaurant/", include(restaurant_browser_urls)),
    path("api/", include("api.urls")),
    path("api/restaurant/", include("restaurant.urls")),
]
