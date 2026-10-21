from django.urls import path
from . import views


app_name = "organizations"
urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("org/", views.dashboard, name="index"),
    path("org/<slug:org_slug>/settings/", views.organization_settings, name="settings"),
    path("org/<slug:org_slug>/people/", views.organization_people, name="people"),
    path("org/<slug:org_slug>/", views.organization_detail, name="detail"),
    path("api/orgs/", views.api_organizations, name="api-orgs"),
    path("api/orgs/<slug:org_slug>/documents/", views.api_documents, name="api-documents"),
    path("api/orgs/<slug:org_slug>/documents/<int:document_id>/", views.api_document_detail, name="api-document-detail"),
]
