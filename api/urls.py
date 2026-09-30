from django.urls import include, path

urlpatterns = [
    path("", include("chat.urls")),
    path("", include("restaurant.urls")),
]
