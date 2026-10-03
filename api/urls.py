from django.urls import include, path

urlpatterns = [
    path("", include("chat.urls")),
    path("chat/", include("chat.urls")),
    path("", include("restaurant.urls")),
    path("restaurant/", include("restaurant.urls")),
]
