import json
from organizations.models import OrganizationMembership


"""Shared presentation context for organization settings dialogs."""


def prepare_organization_settings(organization, user):
    organization.dashboard_members = list(organization.memberships.all())
    organization.members_count = len(organization.dashboard_members)
    organization.dashboard_role = next(
        (item.get_role_display() for item in organization.dashboard_members if item.user_id == user.pk),
        "Member",
    )
    organization.dashboard_address = (organization.profile_data or {}).get("address", "")
    organization.dashboard_is_owner = organization.created_by_id == user.pk
    organization.dashboard_can_edit = any(
        item.user_id == user.pk and item.role in (OrganizationMembership.ROLE_ADMIN, OrganizationMembership.ROLE_MANAGER)
        for item in organization.dashboard_members
    )
    organization.dashboard_can_manage_members = any(
        item.user_id == user.pk and item.role == OrganizationMembership.ROLE_ADMIN
        for item in organization.dashboard_members
    )
    organization.dashboard_can_transfer = organization.dashboard_is_owner or (
        not organization.created_by_id and organization.dashboard_can_manage_members
    )
    organization.dashboard_can_archive = organization.dashboard_is_owner or organization.dashboard_can_manage_members
    organization.dashboard_can_delete = organization.dashboard_is_owner or (
        not organization.created_by_id and organization.dashboard_can_manage_members
    ) or user.is_superuser
    organization.dashboard_transfer_targets = [
        item for item in organization.dashboard_members if item.user_id != user.pk
    ]
    organization.profile_data_json = json.dumps(organization.profile_data or {})
    return organization
