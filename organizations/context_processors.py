from .models import OrganizationMembership


def organization_navigation(request):
    if not getattr(request.user, "is_authenticated", False):
        return {"navigation_organizations": [], "active_navigation_organization": None}
    memberships = list(
        OrganizationMembership.objects.filter(user=request.user)
        .select_related("organization")
        .order_by("organization__name")
    )
    organizations = [
        membership.organization for membership in memberships
        if not (membership.organization.name == "My Business" and membership.organization.slug == "my-business" and membership.organization.created_by_id is None)
    ]
    is_dashboard = getattr(getattr(request, "resolver_match", None), "url_name", None) == "dashboard"
    personal_space = is_dashboard and request.GET.get("space") == "personal"
    personal_tab = ("submissions" if request.GET.get("tab") == "submissions" else "forms") if personal_space else ""
    selected_slug = (
        getattr(getattr(request, "resolver_match", None), "kwargs", {}).get("org_slug")
        or request.GET.get("org")
        or request.session.get("active_organization_slug")
    )
    active = None if personal_space else next((organization for organization in organizations if organization.slug == selected_slug), None)
    if active is None and organizations and not personal_space:
        active = organizations[0]
    workspace_organization = active or next(
        (organization for organization in organizations if organization.slug == selected_slug),
        organizations[0] if organizations else None,
    )
    active_membership = next((membership for membership in memberships if active and membership.organization_id == active.pk), None)
    return {
        "navigation_organizations": organizations,
        "active_navigation_organization": active,
        "workspace_navigation_organization": workspace_organization,
        "active_navigation_role": active_membership.role if active_membership else "",
        "personal_space": personal_space,
        "personal_tab": personal_tab,
    }
