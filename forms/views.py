import csv
import io
import json
import re
import secrets
import zipfile
import xml.etree.ElementTree as ElementTree
from datetime import timedelta
from pathlib import Path
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import AnonRateThrottle
from rest_framework.response import Response
from django.db.models.functions import ExtractHour, TruncHour
from organizations.models import Organization, OrganizationMembership
from organizations.permissions import require_membership, visible_forms, require_form_manage, require_form_records, require_form_response, can_respond_to_form
from orgforms.upload_validation import validate_private_document
from forms.models import DynamicForm, FormSubmission, SubmissionAttachment, Catalog, CatalogItem, ItemSelection
from forms.forms import FormAccessSettingsForm
from forms.serializers import DynamicFormSerializer, CatalogItemCreateSerializer
from ai_gateway.classification import classify_text
from forms.services import validate_form_schema, validate_submission, normalize_schema, save_item_selections
from accounts.models import UserPortfolio
from ai_gateway.models import AIConfiguration
from ai_gateway.services import classify_remote, generate_json


class PublicClassificationThrottle(AnonRateThrottle):
    scope = "public_classify"


_MAX_XLSX_EXPANDED_SIZE = 24 * 1024 * 1024
_MAX_XLSX_ENTRY_SIZE = 12 * 1024 * 1024
_MAX_XLSX_ENTRIES = 5000
_MAX_XLSX_ROWS = 2000
_MAX_XLSX_COLUMNS = 100


def _safe_csv_cell(value):
    """Keep spreadsheet software from evaluating respondent supplied cells."""
    if isinstance(value, str) and (
        value.startswith(("\t", "\r", "\n"))
        or value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@"))
    ):
        return "'" + value
    return value


@login_required
@xframe_options_sameorigin
def form_editor(request, org_slug, form_id=None):
    organization = get_object_or_404(Organization, slug=org_slug)
    membership = require_membership(request.user, organization)
    if organization.is_archived:
        messages.error(request, "Restore this organization before editing its forms.")
        return redirect("organizations:settings", org_slug=organization.slug)
    instance = get_object_or_404(DynamicForm, pk=form_id, organization=organization) if form_id else None
    can_manage_access = membership.role in (OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER)
    if instance:
        require_form_manage(request.user, instance)
    elif not can_manage_access:
        raise PermissionDenied("An organization manager or admin is required to create forms.")
    initial_schema = instance.schema if instance else {"fields": [{"id": "name", "label": "Name", "type": "text", "required": True}]}
    initial_access = {
        "visibility": instance.visibility if instance else DynamicForm.VISIBILITY_ORGANIZATION,
        "access_emails": "\n".join(instance.allowed_users.values_list("email", flat=True)) if instance else "",
    }
    access_settings = FormAccessSettingsForm(request.POST if request.method == "POST" and can_manage_access else None, initial=initial_access)
    def editor(error="", schema=None):
        return render(request, "forms/form_editor.html", {
            "organization": organization, "form": instance,
            "schema_text": request.POST.get("schema", json.dumps(initial_schema, indent=2)),
            "schema_data": schema if schema is not None else initial_schema,
            "title_value": request.POST.get("title", instance.title if instance else ""),
            "description_value": request.POST.get("description", instance.description if instance else ""),
            "purpose_value": request.POST.get("purpose", instance.purpose if instance else ""),
            "slug_value": request.POST.get("slug", instance.slug if instance else ""),
            "status_value": request.POST.get("status", instance.status if instance else DynamicForm.STATUS_DRAFT),
            "restaurant_order": (request.POST.get("include_items") == "on" or request.POST.get("restaurant_order") == "on") if request.method == "POST" else any(field.get("type") == "item_cards" for field in initial_schema.get("fields", [])),
            "access_settings": access_settings, "error": error,
            "can_manage_access": can_manage_access,
            "embedded": request.GET.get("dialog") == "1",
            "base_template": "embedded.html" if request.GET.get("dialog") == "1" else "base.html",
        })
    if request.method != "POST":
        return editor()
    title = request.POST.get("title", "").strip()
    access_valid = access_settings.is_valid() if can_manage_access else True
    try:
        schema = json.loads(request.POST.get("schema", "{}"))
        validate_form_schema(schema)
        if (request.POST.get("include_items") == "on" or request.POST.get("restaurant_order") == "on"):
            schema.setdefault("items_field_id", "items")
            if not any(field.get("id") == schema["items_field_id"] for field in schema["fields"]):
                schema["fields"].append({"id": schema["items_field_id"], "label": "Items", "type": "item_cards", "required": True})
        else:
            schema.pop("restaurant_order", None)
            schema.pop("items_field_id", None)
        schema = normalize_schema(schema, organization)
    except (json.JSONDecodeError, ValidationError, TypeError, AttributeError) as exc:
        return editor(str(exc))
    if not access_valid:
        return editor("Check the sharing settings below.", schema)
    if not title or len(title) > 200:
        return editor("Enter a form title of up to 200 characters.", schema)
    form_slug = slugify(request.POST.get("slug", "") or title)[:180] or "form"
    if form_slug in {"settings", "people", "menu", "submissions", "forms"}:
        return editor("Choose a different link name; this name is reserved for workspace pages.", schema)
    if organization.forms.filter(slug=form_slug).exclude(pk=instance.pk if instance else None).exists():
        return editor("That form URL is already used in this organization.", schema)
    with transaction.atomic():
        form = instance or DynamicForm(organization=organization, created_by=request.user)
        form.title = title
        form.slug = form_slug
        form.description = request.POST.get("description", "").strip()
        form.purpose = request.POST.get("purpose", "").strip()[:120]
        form.schema = schema
        form.status = request.POST.get("status", DynamicForm.STATUS_DRAFT)
        if form.status not in dict(DynamicForm.STATUS_CHOICES):
            form.status = DynamicForm.STATUS_DRAFT
        if can_manage_access:
            form.visibility = access_settings.cleaned_data["visibility"]
        form.save()
        if can_manage_access:
            form.allowed_users.set(access_settings.allowed_accounts)
    messages.success(request, "Form and sharing settings saved.")
    if request.GET.get("dialog") == "1":
        return render(request, "forms/form_saved.html", {"organization": organization})
    return redirect("organizations:detail", org_slug=organization.slug)


@login_required
@xframe_options_sameorigin
def form_submissions(request, org_slug, form_id):
    organization = get_object_or_404(Organization, slug=org_slug)
    require_membership(request.user, organization)
    form = get_object_or_404(DynamicForm, organization=organization, pk=form_id)
    require_form_records(request.user, form)
    submissions = form.submissions.select_related("submitted_by")[:200]
    return render(request, "forms/submissions.html", {
        "organization": organization, "form": form, "submissions": submissions,
        "embedded": request.GET.get("dialog") == "1",
        "base_template": "embedded.html" if request.GET.get("dialog") == "1" else "base.html",
    })


@login_required
def menu_editor(request, org_slug):
    organization = get_object_or_404(Organization, slug=org_slug)
    require_membership(request.user, organization, manage=True)
    if organization.is_archived:
        messages.error(request, "Restore this organization before editing its menu.")
        return redirect("organizations:settings", org_slug=organization.slug)
    business = Catalog.for_organization(organization)
    if request.method == "POST":
        action = request.POST.get("action", "create")
        if action == "availability":
            item = get_object_or_404(CatalogItem, catalog=business, pk=request.POST.get("item_id"))
            item.is_available = not item.is_available
            item.save(update_fields=("is_available", "updated_at"))
        else:
            serializer = CatalogItemCreateSerializer(data={
                "name": request.POST.get("name", "").strip(),
                "category": request.POST.get("category", "General").strip() or "General",
                "description": request.POST.get("description", "").strip(),
                "price": request.POST.get("price", "").strip(),
                "is_available": True,
            })
            if not serializer.is_valid():
                messages.error(request, "Enter a valid item name and non-negative price.")
            else:
                item = serializer.save(catalog=business)
                messages.success(request, f"{item.name} was added to the menu.")
        return redirect("forms:menu", org_slug=organization.slug)
    return render(request, "forms/menu.html", {
        "organization": organization,
        "items": CatalogItem.objects.filter(catalog=business).order_by("category", "name"),
    })


def public_form(request, org_slug, form_slug):
    organization = get_object_or_404(Organization, slug=org_slug, is_archived=False)
    form = get_object_or_404(DynamicForm, organization=organization, slug=form_slug, status=DynamicForm.STATUS_ACTIVE)
    if not can_respond_to_form(request.user, form):
        if not request.user.is_authenticated and request.method == "GET":
            return redirect_to_login(request.get_full_path())
        if request.content_type == "application/json":
            return JsonResponse({"errors": {"detail": "This account does not have access to this form."}}, status=403)
        return render(request, "forms/form_access_denied.html", {
            "organization": organization, "form": form,
        }, status=403)
    schema = normalize_schema(form.schema, organization)
    field_catalogs = {field["id"]: field["catalog_id"] for field in schema["fields"] if field["type"] == "item_cards"}
    menu_items = list(CatalogItem.objects.filter(catalog_id__in=field_catalogs.values(), catalog__organization=organization, is_available=True).values("id", "catalog_id", "name", "category", "description", "price"))
    if request.method == "POST":
        new_file_names = []
        try:
            payload = json.loads(request.body or b"{}") if request.content_type == "application/json" else request.POST.dict()
            if request.content_type and request.content_type.startswith("multipart/form-data") and payload.get("data"):
                payload["data"] = json.loads(payload["data"])
            if not isinstance(payload, dict):
                raise ValidationError("The response must be a JSON object.")
            data = payload.get("data", payload)
            if not isinstance(data, dict):
                raise ValidationError("The response data must be an object.")
            edit_token = payload.get("edit_token")
            edit_sessions = request.session.get("public_form_edit_tokens", {})
            existing_submission_id = edit_sessions.get(str(edit_token)) if edit_token and isinstance(edit_sessions, dict) else None
            existing_file_ids = set(SubmissionAttachment.objects.filter(
                submission_id=existing_submission_id, submission__form=form
            ).values_list("field_id", flat=True)) if existing_submission_id else set()
            uploaded_files = {}
            for field in form.schema.get("fields", []):
                if field.get("type") != "file":
                    continue
                field_id = field["id"]
                uploaded = request.FILES.get(field_id)
                if uploaded:
                    upload_error = validate_private_document(uploaded)
                    if upload_error:
                        raise ValidationError({field_id: upload_error})
                    uploaded_files[field_id] = uploaded
                    data[field_id] = "Uploaded document"
                elif field_id in existing_file_ids:
                    data[field_id] = "Uploaded document"
                else:
                    data[field_id] = ""
            data = validate_submission(form, data)
            with transaction.atomic():
                submission = None
                if not isinstance(edit_sessions, dict):
                    edit_sessions = {}
                if edit_token:
                    submission_id = edit_sessions.get(str(edit_token))
                    if not submission_id:
                        raise ValidationError("This response can no longer be edited. Submit a new response instead.")
                    submission = FormSubmission.objects.select_for_update().filter(
                        pk=submission_id, form=form, organization=organization
                    ).first()
                    if not submission:
                        raise ValidationError("This response can no longer be edited. Submit a new response instead.")
                submission_data = data
                if submission:
                    submission.data = submission_data
                    submission.respondent_name = str(payload.get("respondent_name", ""))[:200]
                    submission.respondent_email = str(payload.get("respondent_email", ""))[:254]
                    submission.save(update_fields=("data", "respondent_name", "respondent_email"))
                else:
                    submission = FormSubmission.objects.create(
                        organization=organization, form=form, data=submission_data,
                        respondent_name=str(payload.get("respondent_name", ""))[:200],
                        respondent_email=str(payload.get("respondent_email", ""))[:254],
                        submitted_by=request.user if request.user.is_authenticated else None,
                    )
                selections = save_item_selections(form, submission, data, payload)
                if selections:
                    submission.data = {**data, "order_id": selections[0].pk}
                    submission.save(update_fields=("data",))
                for field_id, uploaded in uploaded_files.items():
                    previous = SubmissionAttachment.objects.filter(submission=submission, field_id=field_id)
                    previous_file_names = [attachment.file.name for attachment in previous if attachment.file]
                    previous.delete()
                    attachment = SubmissionAttachment(
                        submission=submission,
                        field_id=field_id,
                        original_name=Path(uploaded.name).name[:255],
                        file=uploaded,
                    )
                    try:
                        attachment.save()
                    except Exception:
                        if attachment.file.name:
                            default_storage.delete(attachment.file.name)
                        raise
                    new_file_names.append(attachment.file.name)
                    if previous_file_names:
                        transaction.on_commit(
                            lambda names=tuple(previous_file_names): [default_storage.delete(name) for name in names],
                            robust=True,
                        )
                if request.user.is_authenticated:
                    portfolio = UserPortfolio.objects.filter(user=request.user, auto_update_from_submissions=True).first()
                    if portfolio:
                        profile_data = portfolio.profile_data if isinstance(portfolio.profile_data, dict) else {}
                        field_labels = {field.get("id"): field.get("label", field.get("id")) for field in form.schema.get("fields", [])}
                        saved_answers = {}
                        for key, value in list(data.items())[:40]:
                            if next((field.get("type") for field in form.schema.get("fields", []) if field.get("id") == key), "") == "file":
                                continue
                            if value in (None, "", [], {}) or not isinstance(value, (str, int, float, bool)):
                                continue
                            saved_answers[field_labels.get(str(key), str(key))[:100]] = value[:160] if isinstance(value, str) else value
                        if saved_answers:
                            submissions = profile_data.get("submitted_details", {})
                            if not isinstance(submissions, dict):
                                submissions = {}
                            submissions[form.slug] = {"form": form.title, "updated": timezone.localdate().isoformat(), "answers": saved_answers}
                            profile_data["submitted_details"] = dict(list(submissions.items())[-10:])
                            while len(json.dumps(profile_data, ensure_ascii=False)) > 20000 and profile_data["submitted_details"]:
                                oldest = next(iter(profile_data["submitted_details"]))
                                if oldest == form.slug and len(profile_data["submitted_details"]) == 1:
                                    break
                                profile_data["submitted_details"].pop(oldest)
                            portfolio.profile_data = profile_data
                            portfolio.save(update_fields=("profile_data", "updated_at"))
                edit_token = str(edit_token or secrets.token_urlsafe(32))
                edit_sessions[str(edit_token)] = submission.pk
                request.session["public_form_edit_tokens"] = dict(list(edit_sessions.items())[-20:])
                can_edit_response = True
                can_edit_response = all(selection.status == ItemSelection.STATUS_PENDING and selection.payment_status == ItemSelection.PAYMENT_PENDING for selection in selections)
        except (json.JSONDecodeError, ValidationError) as exc:
            for name in new_file_names:
                default_storage.delete(name)
            if request.content_type == "application/json":
                return JsonResponse({"errors": getattr(exc, "message_dict", {"detail": str(exc)})}, status=400)
            messages.error(request, str(exc))
        except Exception:
            for name in new_file_names:
                default_storage.delete(name)
            raise
        else:
            if request.content_type == "application/json":
                return JsonResponse({"success": True, "submission_id": submission.pk,
                                     "edit_token": edit_token if can_edit_response else "",
                                     "can_edit": can_edit_response}, status=200 if payload.get("edit_token") else 201)
            messages.success(request, "Your response has been submitted.")
            return redirect("forms:public-form", org_slug=org_slug, form_slug=form_slug)
    return render(request, "forms/public_form.html", {
        "organization": organization, "form": form, "menu_items": menu_items, "field_catalogs": field_catalogs,
        "portfolio_assistance_enabled": bool(request.user.is_authenticated and UserPortfolio.objects.filter(user=request.user, use_for_form_assistance=True).exists()),
    })


@api_view(["GET", "POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_forms(request, org_slug):
    organization = get_object_or_404(Organization, slug=org_slug)
    if request.method == "GET":
        require_membership(request.user, organization)
        forms = visible_forms(request.user, organization)
        return Response(DynamicFormSerializer(forms, many=True, context={"request": request}).data)
    require_membership(request.user, organization, manage=True)
    if organization.is_archived:
        return Response({"detail": "Restore this organization before changing forms."}, status=400)
    serializer = DynamicFormSerializer(data=request.data, context={"request": request, "organization": organization})
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        form = serializer.save(organization=organization, created_by=request.user)
    return Response(DynamicFormSerializer(form, context={"request": request}).data, status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_form_detail(request, form_id):
    form = get_object_or_404(DynamicForm.objects.select_related("organization"), pk=form_id)
    membership = require_form_manage(request.user, form)
    privileged = membership.role in (OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER)
    if not privileged and ({"visibility", "access_emails", "access_groups"} & set(request.data.keys())):
        return Response({"detail": "Only an organization manager or admin can change respondent access."}, status=403)
    if form.organization.is_archived:
        return Response({"detail": "Restore this organization before changing forms."}, status=400)
    if request.method == "DELETE":
        if not privileged:
            return Response({"detail": "Only an organization manager or admin can delete forms."}, status=403)
        if form.submissions.exists():
            return Response({"detail": "Archive forms with responses to preserve their records."}, status=409)
        form.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    serializer = DynamicFormSerializer(form, data=request.data, partial=True, context={"request": request})
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        form = serializer.save()
    return Response(DynamicFormSerializer(form, context={"request": request}).data)


@api_view(["PUT"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_form_editors(request, form_id):
    form = get_object_or_404(DynamicForm.objects.select_related("organization"), pk=form_id)
    membership = require_membership(request.user, form.organization)
    if membership.role not in (OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER):
        return Response({"detail": "Only an organization manager or admin can change form editors."}, status=403)
    if form.organization.is_archived:
        return Response({"detail": "Restore this organization before changing form editors."}, status=400)
    editor_ids = request.data.get("editors", [])
    if not isinstance(editor_ids, list) or len(editor_ids) > 100:
        return Response({"detail": "Choose up to 100 organization members as form editors."}, status=400)
    try:
        editor_ids = {int(editor_id) for editor_id in editor_ids}
    except (TypeError, ValueError):
        return Response({"detail": "Editor IDs must be valid account IDs."}, status=400)
    memberships = list(form.organization.memberships.filter(user__is_active=True, user_id__in=editor_ids).select_related("user"))
    if len(memberships) != len(editor_ids):
        return Response({"detail": "Every form editor must be an active member of this organization."}, status=400)
    form.editors.set([item.user for item in memberships])
    return Response({"success": True, "editors": [item.user.email or item.user.username for item in memberships]})


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_form_transfer(request, form_id):
    """Reassign a form owner or move a form and its response history."""
    form = get_object_or_404(DynamicForm.objects.select_related("organization"), pk=form_id)
    source_membership = require_membership(request.user, form.organization)
    if source_membership.role != OrganizationMembership.ROLE_ADMIN:
        return Response({"detail": "Only an organization admin can transfer a form."}, status=403)
    if form.organization.is_archived:
        return Response({"detail": "Restore this organization before transferring forms."}, status=400)
    target = get_object_or_404(Organization, slug=request.data.get("organization", ""), is_archived=False)
    target_membership = OrganizationMembership.objects.filter(
        organization=target, user=request.user, role=OrganizationMembership.ROLE_ADMIN
    ).first()
    if not target_membership:
        return Response({"detail": "You must be an admin of the destination organization."}, status=403)
    new_owner_membership = get_object_or_404(
        OrganizationMembership.objects.select_related("user"),
        pk=request.data.get("owner_membership"), organization=target,
        role__in=(OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER),
    )
    old_org = form.organization
    if old_org.pk != target.pk:
        item_fields = [field for field in form.schema.get("fields", []) if field.get("type") == "item_cards"]
        if item_fields:
            if form.submissions.exists():
                return Response({"detail": "Archive or duplicate a catalog form with responses before moving it; its historical item records remain in their original organization."}, status=409)
            catalog_map = request.data.get("catalog_map", {})
            if not isinstance(catalog_map, dict) or any(str(field.get("catalog_id")) not in catalog_map for field in item_fields):
                return Response({"detail": "Provide catalog_map from each source catalog ID to a catalog in the destination organization."}, status=400)
            for field in item_fields:
                field["catalog_id"] = catalog_map[str(field["catalog_id"])]
            try:
                form.schema = normalize_schema(form.schema, target)
            except (ValidationError, ValueError, TypeError):
                return Response({"detail": "Choose catalogs belonging to the destination organization."}, status=400)
        base_slug = form.slug
        candidate = base_slug
        suffix = 2
        while target.forms.filter(slug=candidate).exclude(pk=form.pk).exists():
            tail = f"-{suffix}"
            candidate = f"{base_slug[:180-len(tail)]}{tail}"
            suffix += 1
        with transaction.atomic():
            form.organization = target
            form.slug = candidate
            form.created_by = new_owner_membership.user
            form.save(update_fields=("organization", "slug", "schema", "created_by", "updated_at"))
            FormSubmission.objects.filter(form=form).update(organization=target)
            target_member_ids = target.memberships.values_list("user_id", flat=True)
            editors_to_remove = list(
                form.editors.exclude(pk__in=target_member_ids).values_list("pk", flat=True)
            )
            if editors_to_remove:
                form.editors.remove(*editors_to_remove)
    else:
        form.created_by = new_owner_membership.user
        form.save(update_fields=("created_by", "updated_at"))
    return Response({
        "success": True,
        "organization": target.name,
        "owner": new_owner_membership.user.email or new_owner_membership.user.username,
        "url": f"/org/{target.slug}/{form.slug}/",
    })


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_submissions(request, form_id):
    form = get_object_or_404(DynamicForm.objects.select_related("organization"), pk=form_id)
    require_form_records(request.user, form)
    data = [{"id": item.pk, "data": item.data, "submitted_at": item.created_at} for item in form.submissions.all()[:500]]
    return Response(data)


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_classify(request):
    text = request.data.get("text", "")
    fields = request.data.get("fields", [])
    if not isinstance(fields, list) or not fields:
        return Response({"detail": "fields must be a non-empty list."}, status=400)
    result = classify_remote([str(text)], fields)
    return Response({"success": True, "model": "remote-system1", "classifications": result} if result else classify_text(text, fields))


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([])
@throttle_classes([PublicClassificationThrottle])
def api_public_classify(request, form_id):
    form = get_object_or_404(
        DynamicForm,
        pk=form_id,
        status=DynamicForm.STATUS_ACTIVE,
        organization__is_archived=False,
    )
    require_form_response(request.user, form)
    text = request.data.get("text", "")
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        return Response({"detail": "Enter a response of up to 2,000 characters."}, status=400)
    fields = form.schema.get("fields", [])
    if request.data.get("use_saved_profile") is True and request.user.is_authenticated:
        portfolio = UserPortfolio.objects.filter(user=request.user, use_for_form_assistance=True).first()
        if portfolio:
            # Only user-entered profile facts are used. Personal document files are never read here.
            facts = {"phone_number": portfolio.phone_number, **(portfolio.profile_data or {})}
            text += "\n" + "; ".join(f"{key.replace('_', ' ')}: {value}" for key, value in facts.items() if value not in (None, "", [], {}))
    return Response(classify_text(text, fields))


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_form_draft(request, org_slug):
    organization = get_object_or_404(Organization, slug=org_slug)
    membership = require_membership(request.user, organization)
    if organization.is_archived:
        return Response({"detail": "Restore this organization before drafting forms."}, status=400)
    prompt = str(request.data.get("prompt", "")).strip()
    if not prompt:
        return Response({"detail": "Describe the form you want to create."}, status=400)
    mode = request.data.get("mode", "form")
    if mode not in {"form", "questions"}:
        return Response({"detail": "Unsupported drafting mode."}, status=400)
    form_id = request.data.get("form_id")
    if mode == "questions" and form_id:
        target_form = get_object_or_404(DynamicForm, pk=form_id, organization=organization)
        require_form_manage(request.user, target_form)
    elif membership.role not in (OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER):
        return Response({"detail": "An organization manager or admin is required to draft new forms."}, status=403)
    profile = AIConfiguration.for_organization(organization)
    category = organization.category_display
    existing_forms = []
    for existing_form in organization.forms.exclude(status=DynamicForm.STATUS_ARCHIVED).order_by("-updated_at")[:12]:
        existing_forms.append({
            "title": existing_form.title,
            "description": existing_form.description[:500],
            "purpose": existing_form.purpose,
            "fields": [
                {"label": field.get("label", ""), "type": field.get("type", "text")}
                for field in (existing_form.schema or {}).get("fields", [])[:30]
            ],
        })
    organization_context = {
        "name": organization.name,
        "category": category,
        "description": organization.description[:1000],
        "purpose": organization.purpose,
        "details": organization.profile_data or {},
        "existing_forms": existing_forms,
        "menu_items": [],
    }
    organization_context["menu_items"] = list(CatalogItem.objects.filter(catalog__organization=organization, is_available=True).values("id", "name", "category", "description", "price")[:50])
    for item in organization_context["menu_items"]:
        item["price"] = str(item["price"])
    request_context = {
        "request": prompt,
        "organization": organization_context,
    }
    if mode == "questions":
        current_form = request.data.get("current_form", {})
        if not isinstance(current_form, dict):
            current_form = {}
        request_context["current_form"] = {
            "title": str(current_form.get("title", ""))[:200],
            "description": str(current_form.get("description", ""))[:1000],
            "purpose": str(current_form.get("purpose", ""))[:200],
            "questions": [
                {"id": str(field.get("id", ""))[:80], "label": str(field.get("label", ""))[:200],
                 "type": str(field.get("type", "text"))[:30]}
                for field in current_form.get("questions", [])[:100]
                if isinstance(field, dict)
            ] if isinstance(current_form.get("questions", []), list) else [],
        }
    contextual_prompt = json.dumps(request_context, ensure_ascii=False, default=str)
    try:
        if mode == "questions":
            generated = generate_json(
                profile, contextual_prompt,
                "Suggest additional, context-specific form questions using the request, current form, and organization metadata. Treat form creation as one coherent set of questions: do not repeat existing questions, avoid generic Name/Details fields unless essential, and ask only for information needed for this specific workflow. Return JSON only: {fields}. Each field needs id, label, type, required. Allowed types: text, textarea, number, email, tel, select, radio, date, checkbox, rating.",
            )
            fields = generated.get("fields", [])
            validate_form_schema({"fields": fields})
            reserved = {str(field.get("id", "")) for field in request_context["current_form"]["questions"]}
            for field in fields:
                base_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(field["id"])).strip("_-") or "question"
                if not base_id[0].isalpha():
                    base_id = f"question_{base_id}"
                candidate, suffix = base_id[:80], 2
                while candidate in reserved:
                    tail = f"_{suffix}"
                    candidate = f"{base_id[:80-len(tail)]}{tail}"
                    suffix += 1
                field["id"] = candidate
                reserved.add(candidate)
            validate_form_schema({"fields": fields})
            return Response({"success": True, "form": {"fields": fields}})
        generated = generate_json(
            profile, contextual_prompt,
            "Draft a coherent, contextual intake form using the user's request and organization metadata. Use the organization's category, purpose, profile details, available menu items (including their names and prices), and existing forms when relevant. A form is a cohesive set of questions: avoid generic Name/Details fields unless essential, avoid duplicating existing forms, and do not invent organization facts or menu items. Return JSON only: {title, description, purpose, fields}. "
        "Each field needs id, label, type, required. Allowed types: text, textarea, number, email, tel, select, radio, date, checkbox, rating, file, item_cards.",
        )
        validate_form_schema({"fields": generated.get("fields", [])})
        return Response({"success": True, "form": generated})
    except Exception:
        if mode == "questions":
            return Response({"success": True, "source": "starter-questions", "form": {"fields": [
                {"id": "workflow_details", "label": f"Details for {category.lower()} request", "type": "textarea", "required": True},
            ]}})
        return Response({"success": True, "source": "deterministic-template", "form": {
            "title": prompt[:120], "description": prompt, "purpose": organization.purpose,
            "fields": [{"id": "name", "label": "Name", "type": "text", "required": True},
                       {"id": "details", "label": "Details", "type": "textarea", "required": True}],
        }})


def _xlsx_rows(upload):
    """Read the first worksheet of an .xlsx file using Python's standard library."""
    spreadsheet_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    document_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    with zipfile.ZipFile(upload) as archive:
        entries = archive.infolist()
        if (
            len(entries) > _MAX_XLSX_ENTRIES
            or sum(entry.file_size for entry in entries) > _MAX_XLSX_EXPANDED_SIZE
            or any(entry.file_size > _MAX_XLSX_ENTRY_SIZE for entry in entries)
        ):
            raise ValueError("The Excel file expands beyond the import size limits.")
        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = ["".join(text.text or "" for text in item.findall(f".//{{{spreadsheet_ns}}}t")) for item in root.findall(f"{{{spreadsheet_ns}}}si")]
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        sheet = workbook.find(f".//{{{spreadsheet_ns}}}sheet")
        if sheet is None:
            return []
        relationship_id = sheet.attrib.get(f"{{{document_ns}}}id")
        relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next((rel.attrib.get("Target") for rel in relationships.findall(f"{{{package_ns}}}Relationship") if rel.attrib.get("Id") == relationship_id), None)
        if not target:
            return []
        sheet_path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
        root = ElementTree.fromstring(archive.read(sheet_path))
        rows = []
        for row_node in root.findall(f".//{{{spreadsheet_ns}}}sheetData/{{{spreadsheet_ns}}}row"):
            if len(rows) >= _MAX_XLSX_ROWS:
                raise ValueError(f"The Excel file can contain at most {_MAX_XLSX_ROWS} rows.")
            row = []
            for cell in row_node.findall(f"{{{spreadsheet_ns}}}c"):
                address = re.match(r"([A-Z]+)", cell.attrib.get("r", "A1"))
                column = 0
                for letter in address.group(1) if address else "A":
                    column = column * 26 + ord(letter) - 64
                column -= 1
                if column >= _MAX_XLSX_COLUMNS:
                    raise ValueError(f"The Excel file can contain at most {_MAX_XLSX_COLUMNS} columns.")
                while len(row) <= column:
                    row.append("")
                value_node = cell.find(f"{{{spreadsheet_ns}}}v")
                value = value_node.text if value_node is not None else ""
                if cell.attrib.get("t") == "s" and value:
                    value = shared_strings[int(value)]
                elif cell.attrib.get("t") == "inlineStr":
                    value = "".join(text.text or "" for text in cell.findall(f".//{{{spreadsheet_ns}}}t"))
                row[column] = value or ""
            rows.append(row)
        return rows


def _schema_from_table(rows):
    if not rows:
        raise ValueError("The uploaded file contains no questions.")
    normalized = [str(value or "").strip() for value in rows[0]]
    header_keys = {value.lower().replace(" ", "_"): index for index, value in enumerate(normalized)}
    has_headers = bool(set(header_keys) & {"label", "question", "name", "title", "type", "required", "options"})
    if has_headers:
        headers, data_rows = header_keys, rows[1:]
    else:
        headers, data_rows = {"label": 0}, rows
    fields = []
    used = set()
    for row in data_rows:
        if not row or not any(str(value or "").strip() for value in row):
            continue
        def cell(*keys, default=""):
            index = next((headers[key] for key in keys if key in headers), None)
            return str(row[index] if index is not None and index < len(row) else default).strip()
        label = cell("label", "question", "name", "title")
        if not label:
            continue
        base = re.sub(r"[^A-Za-z0-9_-]+", "_", label).strip("_-") or "question"
        if not base[0].isalpha():
            base = f"question_{base}"
        field_id, suffix = base[:80], 2
        while field_id in used:
            tail = f"_{suffix}"
            field_id, suffix = f"{base[:80-len(tail)]}{tail}", suffix + 1
        used.add(field_id)
        kind = cell("type").lower() or "text"
        if kind not in {"text", "textarea", "number", "email", "tel", "select", "radio", "date", "checkbox", "rating", "file", "item_cards"}:
            kind = "text"
        required = cell("required").lower() in {"1", "true", "yes", "required"}
        field = {"id": field_id, "label": label[:200], "type": kind, "required": required}
        if kind in {"select", "radio"}:
            field["options"] = [option.strip() for option in re.split(r"[,;|]", cell("options")) if option.strip()]
        fields.append(field)
    schema = {"fields": fields}
    validate_form_schema(schema)
    return schema


@api_view(["POST"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def api_form_schema_import(request, org_slug):
    organization = get_object_or_404(Organization, slug=org_slug)
    membership = require_membership(request.user, organization)
    form_id = request.data.get("form_id")
    if form_id:
        target_form = get_object_or_404(DynamicForm, pk=form_id, organization=organization)
        require_form_manage(request.user, target_form)
    elif membership.role not in (OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER):
        return Response({"detail": "An organization manager or admin is required to import a new form schema."}, status=403)
    upload = request.FILES.get("file")
    if not upload or upload.size > 2 * 1024 * 1024:
        return Response({"detail": "Choose a CSV, Excel (.xlsx), or JSON schema file up to 2 MB."}, status=400)
    suffix = upload.name.lower().rsplit(".", 1)[-1] if "." in upload.name else ""
    try:
        if suffix == "json":
            payload = json.loads(upload.read().decode("utf-8-sig"))
            schema = payload if isinstance(payload, dict) else {"fields": payload}
            validate_form_schema(schema)
        elif suffix == "csv":
            rows = list(csv.reader(io.StringIO(upload.read().decode("utf-8-sig"))))
            schema = _schema_from_table(rows)
        elif suffix == "xlsx":
            schema = _schema_from_table(_xlsx_rows(upload))
        else:
            return Response({"detail": "Supported schema files are CSV, Excel (.xlsx), and JSON."}, status=400)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, KeyError, IndexError, zipfile.BadZipFile, ElementTree.ParseError, ValidationError) as error:
        message = error.messages[0] if isinstance(error, ValidationError) else str(error)
        return Response({"detail": message or "Could not read this schema file."}, status=400)
    return Response({"success": True, "schema": schema})


@login_required
def submission_attachment(request, attachment_id):
    attachment = get_object_or_404(SubmissionAttachment.objects.select_related("submission__form"), pk=attachment_id)
    require_form_records(request.user, attachment.submission.form)
    try:
        stream = attachment.file.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404
    return FileResponse(stream, as_attachment=True, filename=attachment.original_name)


@login_required
def organization_submissions(request, org_slug):
    organization = get_object_or_404(Organization, slug=org_slug, is_archived=False)
    membership = require_membership(request.user, organization)
    can_review = membership.role in {OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER}
    now = timezone.now()
    local_now = timezone.localtime(now)
    today = local_now.date()
    accessible_forms = visible_forms(request.user, organization)
    recent = organization.submissions.filter(form__in=accessible_forms)
    form_id = request.GET.get("form", "")
    selected_form = None
    if form_id:
        from uuid import UUID
        from django.http import Http404
        try:
            form_id = UUID(form_id)
        except (ValueError, TypeError):
            raise Http404
        selected_form = get_object_or_404(accessible_forms, pk=form_id)
        recent = recent.filter(form=selected_form)

    period = request.GET.get("period", "30d")
    if period not in {"24h", "7d", "30d", "90d"}:
        period = "30d"
    grain = request.GET.get("grain", "day")
    if grain not in {"hour", "day", "shift"}:
        grain = "day"
    selected_status = request.GET.get("status", "")
    valid_statuses = {value for value, _label in FormSubmission.STATUS_CHOICES}
    if selected_status not in valid_statuses:
        selected_status = ""

    if grain == "hour":
        period = "24h"
        recent = recent.filter(created_at__gte=now - timedelta(hours=24))
        period_label = "Past 24 hours"
    elif period == "24h":
        recent = recent.filter(created_at__gte=now - timedelta(hours=24))
        first_day = (local_now - timedelta(hours=24)).date()
        days = (today - first_day).days + 1
        period_label = "Past 24 hours"
    else:
        days = {"7d": 7, "30d": 30, "90d": 90}[period]
        first_day = today - timedelta(days=days - 1)
        recent = recent.filter(created_at__date__gte=first_day, created_at__date__lte=today)
        period_label = f"Past {days} days"
    pending_count = recent.filter(status=FormSubmission.STATUS_PENDING).count()
    if selected_status:
        recent = recent.filter(status=selected_status)

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{organization.slug}-submissions.csv"'
        writer = csv.writer(response)
        writer.writerow(("Submission ID", "Received at", "Form", "Respondent", "Email", "Status", "Response JSON"))
        for item in recent.select_related("form", "submitted_by").order_by("-created_at")[:5000]:
            writer.writerow((item.pk, timezone.localtime(item.created_at).isoformat(), _safe_csv_cell(item.form.title), _safe_csv_cell(item.respondent_name), _safe_csv_cell(item.respondent_email), item.get_status_display(), json.dumps(item.data, ensure_ascii=False)))
        return response

    total_count = recent.count()
    identified = set()
    for submission_id, user_id, email in recent.values_list("pk", "submitted_by_id", "respondent_email"):
        email = (email or "").strip().lower()
        if email:
            identified.add(f"email:{email}")
        elif user_id:
            identified.add(f"user:{user_id}")

    if grain == "hour":
        start_hour = (local_now - timedelta(hours=23)).replace(minute=0, second=0, microsecond=0)
        hourly_counts = {
            timezone.localtime(row["bucket"]).replace(minute=0, second=0, microsecond=0): row["total"]
            for row in recent.annotate(bucket=TruncHour("created_at")).values("bucket").annotate(total=Count("pk"))
        }
        points = []
        for offset in range(24):
            bucket = start_hour + timedelta(hours=offset)
            points.append({"label": bucket.strftime("%H:%M"), "detail": bucket.strftime("%b %d, %H:00"), "count": hourly_counts.get(bucket, 0)})
        chart_description = "Hourly submissions over the past 24 hours"
    elif grain == "shift":
        shift_counts = {"Morning": 0, "Afternoon": 0, "Evening": 0}
        hourly = recent.annotate(hour=ExtractHour("created_at")).values("hour").annotate(total=Count("pk"))
        for row in hourly:
            hour = row["hour"]
            shift = "Morning" if 6 <= hour < 12 else "Afternoon" if 12 <= hour < 18 else "Evening"
            shift_counts[shift] += row["total"]
        points = [{"label": label, "detail": f"{label} shift · {period_label.lower()}", "count": count} for label, count in shift_counts.items()]
        chart_description = f"Submissions by shift · {period_label.lower()} (morning 06–12, afternoon 12–18, evening 18–06)"
    else:
        daily_counts = {
            row["day"]: row["total"]
            for row in recent.annotate(day=TruncDate("created_at")).values("day").annotate(total=Count("pk"))
        }
        points = []
        for day_offset in range(days):
            day = first_day + timedelta(days=day_offset)
            points.append({"label": day.strftime("%b %-d"), "detail": day.strftime("%b %d, %Y"), "count": daily_counts.get(day, 0)})
        chart_description = "Daily submissions over the past 24 hours" if period == "24h" else f"Daily submissions over the past {days} days"
    peak = max((point["count"] for point in points), default=0)
    trend = [{**point, "height": max(4, round(point["count"] / peak * 100)) if peak else 4} for point in points]

    if request.method == "POST" and request.POST.get("action") == "update-status":
        if not can_review:
            raise PermissionDenied("Only organization admins and managers can update submission status.")
        submission = get_object_or_404(recent, pk=request.POST.get("submission_id"))
        status = request.POST.get("status", "")
        if status not in valid_statuses:
            messages.error(request, "Choose a valid submission status.")
        else:
            submission.status = status
            submission.save(update_fields=("status",))
            messages.success(request, "Submission status updated.")
        query = request.GET.urlencode()
        url = reverse("forms:all-submissions", kwargs={"org_slug": organization.slug})
        return redirect(f"{url}?{query}" if query else url)

    export_params = request.GET.copy()
    export_params["export"] = "csv"
    pending_params = request.GET.copy()
    pending_params.pop("export", None)
    pending_params["status"] = FormSubmission.STATUS_PENDING
    submissions = recent.select_related("form", "submitted_by").prefetch_related("attachments").order_by("-created_at")[:250]
    return render(request, "forms/all_submissions.html", {
        "organization": organization,
        "submissions": submissions,
        "total_count": total_count,
        "identified_respondents": len(identified),
        "active_forms_count": accessible_forms.filter(status="active").count(),
        "daily_rate": round(total_count / {"24h": 1, "7d": 7, "30d": 30, "90d": 90}[period], 2),
        "trend": trend,
        "chart_description": chart_description,
        "selected_period": period,
        "selected_grain": grain,
        "selected_status": selected_status,
        "period_label": period_label,
        "status_choices": FormSubmission.STATUS_CHOICES,
        "can_review": can_review,
        "form_choices": accessible_forms,
        "form_count": accessible_forms.count(),
        "selected_form": selected_form,
        "pending_count": pending_count,
        "pending_query": pending_params.urlencode(),
        "export_query": export_params.urlencode(),
    })


@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAuthenticated])
def catalog_items(request):
    organization = get_object_or_404(Organization, slug=request.headers.get("X-Organization") or request.GET.get("org") or request.session.get("active_organization_slug"))
    require_membership(request.user, organization)
    from .serializers import CatalogItemSerializer
    return Response(CatalogItemSerializer(CatalogItem.objects.filter(catalog__organization=organization, is_available=True), many=True).data)
