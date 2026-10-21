from django.urls import include, path
from organizations import views

handler403 = "organizations.views.access_denied"
urlpatterns = [
    path("", views.home, name="home"),
    path("", include("accounts.urls")),
    path("", include("organizations.urls")),
    path("", include("chat.urls")),
    path("", include("ai_gateway.urls")),
    path("", include("forms.urls")),
]
