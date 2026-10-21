from django.urls import path
from . import views
from .views import configuration


app_name = "ai_gateway"
urlpatterns = [
    path("api/health/", views.health, name="health"),
    path("api/models/", views.models, name="models"),
    path("api/local-model-profiles/", views.local_model_profiles, name="local-model-profiles"),
    path("api/local-model-profiles/<int:profile_id>/", views.local_model_profile_detail, name="local-model-profile-detail"),
    path("api/chat/health/", views.health),
    path("api/chat/models/", views.models),
    path("api/chat/local-model-profiles/", views.local_model_profiles),
    path("api/chat/local-model-profiles/<int:profile_id>/", views.local_model_profile_detail),
    path("api/ai/configuration/", configuration, name="configuration"),
]
