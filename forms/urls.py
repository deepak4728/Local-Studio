from django.urls import path
from . import views


app_name = "forms"
urlpatterns = [
    path("org/submission-files/<int:attachment_id>/", views.submission_attachment, name="submission-attachment"),
    path("org/<slug:org_slug>/submissions/", views.organization_submissions, name="all-submissions"),
    path("org/<slug:org_slug>/forms/new/", views.form_editor, name="form-new"),
    path("org/<slug:org_slug>/forms/<uuid:form_id>/edit/", views.form_editor, name="form-edit"),
    path("org/<slug:org_slug>/forms/<uuid:form_id>/submissions/", views.form_submissions, name="submissions"),
    path("org/<slug:org_slug>/menu/", views.menu_editor, name="menu"),
    path("api/orgs/<slug:org_slug>/forms/", views.api_forms, name="api-forms"),
    path("api/orgs/<slug:org_slug>/form-draft/", views.api_form_draft, name="api-form-draft"),
    path("api/orgs/<slug:org_slug>/schema-import/", views.api_form_schema_import, name="api-form-schema-import"),
    path("api/forms/<uuid:form_id>/", views.api_form_detail, name="api-form-detail"),
    path("api/forms/<uuid:form_id>/transfer/", views.api_form_transfer, name="api-form-transfer"),
    path("api/forms/<uuid:form_id>/editors/", views.api_form_editors, name="api-form-editors"),
    path("api/forms/<uuid:form_id>/classify/", views.api_public_classify, name="api-public-classify"),
    path("api/forms/<uuid:form_id>/submissions/", views.api_submissions, name="api-submissions"),
    path("api/ai/classify/", views.api_classify, name="api-classify"),
    path("api/menu/", views.catalog_items, name="menu-items"),
    path("org/<slug:org_slug>/<slug:form_slug>/", views.public_form, name="public-form"),
]
