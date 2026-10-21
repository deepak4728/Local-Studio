from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from organizations.models import Organization, OrganizationMembership


class Command(BaseCommand):
    help = "Assign the first owner of an unclaimed organization from the local admin shell."

    def add_arguments(self, parser):
        parser.add_argument("organization_slug")
        parser.add_argument("account_email")

    @transaction.atomic
    def handle(self, *args, **options):
        organization = Organization.objects.select_for_update().filter(slug=options["organization_slug"]).first()
        if not organization:
            raise CommandError("Organization not found.")
        if organization.created_by_id or organization.memberships.exists():
            raise CommandError("This organization already has an owner or members. Use its workspace ownership controls.")
        accounts = list(get_user_model().objects.filter(email__iexact=options["account_email"], is_active=True)[:2])
        if len(accounts) != 1:
            raise CommandError("Provide the email of a unique active account.")
        user = accounts[0]
        OrganizationMembership.objects.create(organization=organization, user=user, role="admin")
        organization.created_by = user
        organization.save(update_fields=("created_by", "updated_at"))
        self.stdout.write(self.style.SUCCESS("Organization ownership assigned. Existing records were preserved."))
