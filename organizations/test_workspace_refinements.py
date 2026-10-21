from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from forms.models import DynamicForm
from organizations.models import Organization, OrganizationGroup, OrganizationMembership


class WorkspaceRefinementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user(username="workspace-owner", email="owner@example.test")
        cls.member = User.objects.create_user(username="workspace-member", email="member@example.test")
        cls.outsider = User.objects.create_user(username="workspace-outsider", email="outsider@example.test")
        cls.org = Organization.objects.create(name="Owned team", created_by=cls.owner)
        cls.shared = Organization.objects.create(name="Shared team", created_by=cls.member)
        for org, user, role in ((cls.org, cls.owner, "admin"), (cls.org, cls.member, "member"), (cls.shared, cls.owner, "member"), (cls.shared, cls.member, "admin")):
            OrganizationMembership.objects.create(organization=org, user=user, role=role)
        cls.form = DynamicForm.objects.create(organization=cls.org, title="Team intake", slug="team-intake", created_by=cls.owner)
        cls.group = OrganizationGroup.objects.create(organization=cls.org, name="Reviewers", alias="reviewers")
        cls.group.members.add(cls.member)
        cls.form.allowed_groups.add(cls.group)

    def setUp(self):
        self.client.force_login(self.owner)

    def test_owned_shared_filters_and_scoped_links(self):
        url = reverse("organizations:dashboard")
        owned = self.client.get(url, {"ownership": "owned"})
        self.assertEqual([org.pk for org in owned.context["organizations"]], [self.org.pk])
        self.assertContains(owned, f'/_chat/?org={self.org.slug}')
        self.assertNotContains(owned, "Personal profile")
        shared = self.client.get(url, {"ownership": "shared"})
        self.assertEqual([org.pk for org in shared.context["organizations"]], [self.shared.pk])
        self.org.is_archived = True
        self.org.save(update_fields=["is_archived"])
        archived = self.client.get(url, {"ownership": "owned", "status": "archived"})
        self.assertEqual([org.pk for org in archived.context["organizations"]], [self.org.pk])

    def test_forms_keep_context_and_share_settings_dialog(self):
        response = self.client.get(reverse("organizations:detail", args=[self.org.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<title>Owned team · OrgForms</title>", html=True)
        self.assertContains(response, f'/org/{self.org.slug}/submissions/?form={self.form.pk}')
        self.assertContains(response, f'data-open-manage="{self.org.slug}"')
        self.assertContains(response, f'id="manage-{self.org.slug}"')
        self.assertContains(response, 'name="return_to" value="organization"')
        self.assertContains(response, 'data-form-status-value="draft"')
        response = self.client.post(reverse("organizations:settings", args=[self.org.slug]), {
            "action": "update-details", "return_to": "organization", "name": "Updated team", "business_type": "generic",
        })
        self.assertRedirects(response, reverse("organizations:detail", args=[self.org.slug]) + f'?manage={self.org.slug}&tab=details')

    def test_groups_can_be_edited_without_losing_form_assignments(self):
        response = self.client.post(reverse("organizations:people", args=[self.org.slug]), {
            "action": "update-group", "group_id": self.group.pk,
            "name": "Intake reviewers", "alias": "intake", "members": [self.owner.pk, self.member.pk],
        })
        self.assertEqual(response.status_code, 302)
        self.group.refresh_from_db()
        self.assertEqual(self.group.alias, "intake")
        self.assertSetEqual(set(self.group.members.all()), {self.owner, self.member})
        self.assertTrue(self.form.allowed_groups.filter(pk=self.group.pk).exists())

    def test_group_members_must_belong_to_this_organization(self):
        response = self.client.post(reverse("organizations:people", args=[self.org.slug]), {
            "action": "update-group", "group_id": self.group.pk,
            "name": "Changed", "alias": "changed", "members": [self.outsider.pk],
        })
        self.assertEqual(response.status_code, 302)
        self.group.refresh_from_db()
        self.assertEqual(self.group.alias, "reviewers")
        self.assertSetEqual(set(self.group.members.all()), {self.member})

    def test_group_permissions_and_organization_boundary(self):
        foreign_group = OrganizationGroup.objects.create(organization=self.shared, name="Other group", alias="other")
        response = self.client.post(reverse("organizations:people", args=[self.org.slug]), {
            "action": "update-group", "group_id": foreign_group.pk, "name": "Changed", "alias": "changed",
        })
        self.assertEqual(response.status_code, 404)
        self.client.force_login(self.member)
        response = self.client.post(reverse("organizations:people", args=[self.org.slug]), {
            "action": "update-group", "group_id": self.group.pk, "name": "Changed", "alias": "changed",
        })
        self.assertEqual(response.status_code, 403)

    def test_removing_member_clears_organization_group_membership(self):
        membership = OrganizationMembership.objects.get(organization=self.org, user=self.member)
        response = self.client.post(reverse("organizations:settings", args=[self.org.slug]), {
            "action": "remove-member", "return_to": "people", "membership_id": membership.pk,
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.group.members.filter(pk=self.member.pk).exists())
        self.assertFalse(OrganizationMembership.objects.filter(pk=membership.pk).exists())

    def test_people_and_submissions_render_task_specific_controls(self):
        people = self.client.get(reverse("organizations:people", args=[self.org.slug]))
        self.assertEqual(people.status_code, 200)
        self.assertContains(people, 'data-people-panel="groups"')
        self.assertContains(people, f'id="group-{self.group.pk}"')
        submissions = self.client.get(reverse("forms:all-submissions", args=[self.org.slug]), {"form": self.form.pk})
        self.assertEqual(submissions.status_code, 200)
        self.assertContains(submissions, "Pending review")
        self.assertContains(submissions, "Export CSV")
        self.assertEqual(submissions.context["selected_form"].pk, self.form.pk)

    def test_adding_existing_member_does_not_silently_replace_their_role(self):
        response = self.client.post(reverse("organizations:settings", args=[self.org.slug]), {
            "action": "add-member", "return_to": "people", "email": self.owner.email, "role": "member",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(OrganizationMembership.objects.get(organization=self.org, user=self.owner).role, "admin")
        self.client.post(reverse("organizations:settings", args=[self.org.slug]), {
            "action": "add-member", "return_to": "people", "email": self.member.email, "role": "admin",
        })
        self.assertEqual(OrganizationMembership.objects.get(organization=self.org, user=self.member).role, "member")
