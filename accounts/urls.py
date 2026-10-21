from django.contrib.auth import views as auth_views
from django.urls import path
from . import views


app_name = "accounts"
urlpatterns = [
    path("accounts/signup/", views.signup, name="signup"),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="accounts/login.html"), name="login"),
    path("accounts/logout/", views.logout_view, name="logout"),
    path("accounts/profile/", views.profile, name="profile"),
    path("accounts/profile/documents/<int:document_id>/", views.personal_document, name="personal-document"),
    path("api/profile/portfolio/", views.api_personal_portfolio, name="personal-portfolio"),
]
