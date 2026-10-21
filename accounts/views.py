import json
from pathlib import Path
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.core.files.storage import default_storage
from django.db import transaction
from accounts.models import UserPortfolio, PersonalDocument
from accounts.forms import AccountDetailsForm, RegistrationForm
from orgforms.upload_validation import validate_private_document


def signup(request):
    if request.user.is_authenticated:
        return redirect("organizations:dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        User = get_user_model()
        user = User.objects.create_user(username=email, email=email, password=form.cleaned_data["password1"])
        login(request, user)
        return redirect("organizations:dashboard")
    return render(request, "accounts/signup.html", {"form": form})


def logout_view(request):
    if request.method == "POST":
        logout(request)
        return redirect("accounts:login")
    return HttpResponse(status=405)


@login_required
def profile(request):
    details_form = AccountDetailsForm(instance=request.user, prefix="details")
    password_form = PasswordChangeForm(request.user, prefix="password")
    portfolio, _ = UserPortfolio.objects.get_or_create(user=request.user)
    portfolio_error = ""
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "details":
            details_form = AccountDetailsForm(request.POST, instance=request.user, prefix="details")
            if details_form.is_valid():
                details_form.save()
                messages.success(request, "Your profile details have been updated.")
                return redirect("accounts:profile")
        elif action == "portfolio":
            try:
                data = json.loads(request.POST.get("profile_data", "{}"))
                if not isinstance(data, dict):
                    raise ValueError("Use a JSON object, for example {\"skills\": [\"...\"]}.")
                if len(json.dumps(data, ensure_ascii=False)) > 20000:
                    raise ValueError("Keep your profile portfolio under 20 KB.")
                portfolio.phone_number = request.POST.get("phone_number", "").strip()[:40]
                portfolio.profile_data = data
                portfolio.use_for_form_assistance = request.POST.get("use_for_form_assistance") == "on"
                portfolio.auto_update_from_submissions = request.POST.get("auto_update_from_submissions") == "on"
                portfolio.save()
                messages.success(request, "Your personal portfolio has been saved.")
                return redirect("accounts:profile")
            except (ValueError, TypeError) as error:
                portfolio_error = str(error)
                portfolio.phone_number = request.POST.get("phone_number", "")
                portfolio.profile_data = request.POST.get("profile_data", "{}")
        elif action == "upload-document":
            uploaded = request.FILES.get("file")
            kind = request.POST.get("kind", "other")
            upload_error = validate_private_document(uploaded)
            if upload_error or kind not in {value for value, _label in PersonalDocument.KIND_CHOICES}:
                messages.error(request, upload_error or "Choose a valid document type.")
            else:
                PersonalDocument.objects.create(user=request.user, title=request.POST.get("title", "").strip()[:160] or uploaded.name[:160], kind=kind, file=uploaded)
                messages.success(request, "Private document uploaded.")
            return redirect("accounts:profile")
        elif action == "delete-document":
            document = get_object_or_404(PersonalDocument, pk=request.POST.get("document_id"), user=request.user)
            file_name = document.file.name
            with transaction.atomic():
                document.delete()
                if file_name:
                    transaction.on_commit(lambda: default_storage.delete(file_name), robust=True)
            messages.success(request, "Document removed from your portfolio.")
            return redirect("accounts:profile")
        elif action == "password":
            password_form = PasswordChangeForm(request.user, request.POST, prefix="password")
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Your password has been changed.")
                return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {
        "details_form": details_form,
        "password_form": password_form,
        "portfolio": portfolio,
        "portfolio_json": request.POST.get("profile_data", json.dumps(portfolio.profile_data if isinstance(portfolio.profile_data, dict) else {}, ensure_ascii=False, indent=2)) if request.method == "POST" and request.POST.get("action") == "portfolio" else json.dumps(portfolio.profile_data if isinstance(portfolio.profile_data, dict) else {}, ensure_ascii=False, indent=2),
        "portfolio_error": portfolio_error,
        "personal_documents": PersonalDocument.objects.filter(user=request.user),
    })


@login_required
def personal_document(request, document_id):
    document = get_object_or_404(PersonalDocument, pk=document_id, user=request.user)
    try:
        stream = document.file.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404
    extension = Path(document.file.name).suffix
    filename = document.title if Path(document.title).suffix else f"{document.title}{extension}"
    return FileResponse(stream, as_attachment=True, filename=filename)


@login_required
def api_personal_portfolio(request):
    if request.method != "GET":
        return JsonResponse({"detail": "Method not allowed."}, status=405)
    portfolio = UserPortfolio.objects.filter(user=request.user).first()
    if not portfolio or not portfolio.use_for_form_assistance:
        return JsonResponse({"enabled": False, "detail": "Enable profile use in your profile settings first."})
    return JsonResponse({"enabled": True, "phone_number": portfolio.phone_number, "profile_data": portfolio.profile_data})
