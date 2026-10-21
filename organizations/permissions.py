from django.core.exceptions import PermissionDenied
from django.db.models import Q
from .models import OrganizationMembership


def visible_forms(user, organization):
    """Private workspace visibility; public links never grant workspace access."""
    membership = require_membership(user, organization)
    forms = organization.forms.all()
    if membership.role in (OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER):
        return forms
    return forms.filter(
        ~Q(visibility="restricted")
        | Q(allowed_users=user)
        | Q(allowed_groups__members=user)
        | Q(editors=user)
    ).distinct()


def require_form_records(user, form):
    require_membership(user, form.organization)
    if not visible_forms(user, form.organization).filter(pk=form.pk).exists():
        raise PermissionDenied("You do not have access to this form.")


def can_manage_form(user, form):
    membership = membership_for(user, form.organization)
    if not membership:
        return False
    if membership.role in (OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER):
        return True
    return form.editors.filter(pk=user.pk).exists()


def require_form_manage(user, form):
    if not can_manage_form(user, form):
        raise PermissionDenied("A form editor, organization manager, or admin is required.")
    return membership_for(user, form.organization)


def can_respond_to_form(user, form):
    from forms.models import DynamicForm
    if form.organization.is_archived or form.status != DynamicForm.STATUS_ACTIVE:
        return False
    if form.visibility == DynamicForm.VISIBILITY_PUBLIC:
        return True
    if not getattr(user, "is_authenticated", False):
        return False
    membership = membership_for(user, form.organization)
    if membership and membership.role in (OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER):
        return True
    if form.visibility == DynamicForm.VISIBILITY_ORGANIZATION:
        return membership is not None
    return form.allowed_users.filter(pk=user.pk).exists() or (membership is not None and form.allowed_groups.filter(members=user).exists())


def require_form_response(user, form):
    if not can_respond_to_form(user, form):
        raise PermissionDenied("This form is restricted. Sign in with an account that has access.")


def membership_for(user, organization):
    if not getattr(user, "is_authenticated", False) or not hasattr(user, "_meta"):
        return None
    return OrganizationMembership.objects.filter(user=user, organization=organization).first()


def require_membership(user, organization, *, manage=False):
    membership = membership_for(user, organization)
    if not membership:
        raise PermissionDenied("You are not a member of this organization.")
    if manage and membership.role not in (OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER):
        raise PermissionDenied("An organization manager or admin is required.")
    return membership
