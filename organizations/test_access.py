import json
import tempfile
from io import StringIO
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command, CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from forms.models import Catalog
from forms.models import DynamicForm, FormSubmission
from organizations.models import Organization, OrganizationMembership, OrganizationDocument


class FormAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner, cls.manager, cls.member, cls.guest, cls.stranger = [
            User.objects.create_user(username=f"{name}@test.com", email=f"{name}@test.com", password="secure-test-pass123")
            for name in ("owner", "manager", "member", "guest", "stranger")
        ]
        cls.org = Organization.objects.create(name="Private workspace", created_by=cls.owner)
        for user, role in ((cls.owner, "admin"), (cls.manager, "manager"), (cls.member, "member")):
            OrganizationMembership.objects.create(organization=cls.org, user=user, role=role)
        cls.form = DynamicForm.objects.create(
            organization=cls.org, title="Sensitive feedback", slug="feedback", status="active",
            schema={"fields": [{"id": "note", "label": "Note", "type": "text", "required": True}]},
        )

    def form_url(self):
        return reverse("forms:public-form", args=(self.org.slug, self.form.slug))

    def submit(self):
        return self.client.post(self.form_url(), json.dumps({"data": {"note": "saved response"}}), content_type="application/json")

    def restrict(self):
        self.form.visibility = "restricted"
        self.form.save()
        self.form.allowed_users.set([self.guest])

    def test_workspace_private_even_when_a_form_is_public(self):
        self.form.visibility = "public"
        self.form.save()
        for route in ("organizations:detail", "organizations:settings", "organizations:people", "forms:all-submissions"):
            self.client.force_login(self.stranger)
            response = self.client.get(reverse(route, args=(self.org.slug,)))
            self.assertEqual(response.status_code, 403)
            self.assertNotContains(response, self.form.title, status_code=403)
        self.client.logout()
        self.assertEqual(self.client.get(self.form_url()).status_code, 200)

    def test_default_audience_is_members_only_and_saves_to_database(self):
        self.assertEqual(DynamicForm.objects.get(pk=self.form.pk).visibility, "organization")
        self.assertEqual(self.client.get(self.form_url()).status_code, 302)
        self.assertEqual(self.submit().status_code, 403)
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.form_url()).status_code, 403)
        self.assertEqual(self.submit().status_code, 403)
        self.client.force_login(self.member)
        self.assertEqual(self.submit().status_code, 201)
        saved = FormSubmission.objects.get()
        self.assertEqual(saved.organization_id, self.org.pk)
        self.assertEqual(saved.submitted_by_id, self.member.pk)
        self.assertEqual(saved.data, {"note": "saved response"})

    def test_public_respondents_never_gain_records_or_workspace_access(self):
        self.form.visibility = "public"
        self.form.save()
        self.assertEqual(self.submit().status_code, 201)
        self.client.force_login(self.guest)
        for name, args in (("organizations:detail", (self.org.slug,)), ("forms:api-submissions", (self.form.pk,)), ("forms:api-forms", (self.org.slug,))):
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403)

    def test_selected_external_account_can_respond_but_not_see_organization(self):
        self.restrict()
        self.client.force_login(self.guest)
        self.assertContains(self.client.get(reverse("organizations:dashboard")), "Forms shared with you")
        self.assertEqual(self.client.get(self.form_url()).status_code, 200)
        self.assertEqual(self.submit().status_code, 201)
        self.assertFalse(self.org.memberships.filter(user=self.guest).exists())
        self.assertEqual(self.client.get(reverse("organizations:detail", args=(self.org.slug,))).status_code, 403)
        self.assertEqual(self.client.get(reverse("forms:api-submissions", args=(self.form.pk,))).status_code, 403)

    def test_revoking_account_blocks_get_post_and_classification(self):
        self.restrict()
        self.client.force_login(self.guest)
        url = reverse("forms:api-public-classify", args=(self.form.pk,))
        self.assertEqual(self.client.post(url, {"text": "example"}).status_code, 200)
        self.form.allowed_users.clear()
        self.assertEqual(self.client.get(self.form_url()).status_code, 403)
        self.assertEqual(self.submit().status_code, 403)
        self.assertEqual(self.client.post(url, {"text": "example"}).status_code, 403)
        self.assertFalse(FormSubmission.objects.exists())

    def test_restricted_form_hidden_from_unselected_member_and_analytics(self):
        self.restrict()
        FormSubmission.objects.create(organization=self.org, form=self.form, data={"note": "private content"})
        self.client.force_login(self.member)
        self.assertNotContains(self.client.get(reverse("organizations:detail", args=(self.org.slug,))), self.form.title)
        self.assertEqual(self.client.get(reverse("forms:api-forms", args=(self.org.slug,))).json(), [])
        self.assertEqual(self.client.get(reverse("forms:api-submissions", args=(self.form.pk,))).status_code, 403)
        self.assertEqual(self.client.get(reverse("forms:submissions", args=(self.org.slug, self.form.pk))).status_code, 403)
        analytics = self.client.get(reverse("forms:all-submissions", args=(self.org.slug,)))
        self.assertEqual(analytics.context["total_count"], 0)
        self.assertNotContains(analytics, self.form.title)
        self.assertEqual(self.client.get(reverse("forms:all-submissions", args=(self.org.slug,)), {"form": str(self.form.pk)}).status_code, 404)

    def test_managers_can_manage_and_review_restricted_forms(self):
        self.restrict()
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("forms:form-edit", args=(self.org.slug, self.form.pk))).status_code, 200)
        self.assertEqual(self.client.get(reverse("forms:api-submissions", args=(self.form.pk,))).status_code, 200)

    def test_editor_persists_sharing_and_revokes_old_grants(self):
        self.client.force_login(self.owner)
        url = reverse("forms:form-edit", args=(self.org.slug, self.form.pk))
        data = {"title": self.form.title, "slug": self.form.slug, "schema": json.dumps(self.form.schema), "status": "active", "visibility": "restricted", "access_emails": self.guest.email}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.form.refresh_from_db()
        self.assertEqual(self.form.visibility, "restricted")
        self.assertEqual(list(self.form.allowed_users.all()), [self.guest])
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(url, data).status_code, 403)
        self.client.force_login(self.owner)
        data["visibility"] = "organization"
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertFalse(self.form.allowed_users.exists())

    def test_invalid_invitee_does_not_partially_change_existing_form(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("forms:form-edit", args=(self.org.slug, self.form.pk)), {
            "title": "Should not be saved", "slug": self.form.slug, "schema": json.dumps(self.form.schema),
            "visibility": "restricted", "access_emails": "missing@test.com",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "must have a unique active OrgForms account")
        self.form.refresh_from_db()
        self.assertEqual(self.form.title, "Sensitive feedback")

    def test_api_sharing_persists_and_rejects_nonmanagers(self):
        self.client.force_login(self.owner)
        url = reverse("forms:api-form-detail", args=(self.form.pk,))
        response = self.client.patch(url, json.dumps({"visibility": "restricted", "access_emails": [self.guest.email]}), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["allowed_people"], [self.guest.email])
        self.client.force_login(self.member)
        self.assertEqual(self.client.patch(url, json.dumps({"visibility": "public"}), content_type="application/json").status_code, 403)
        self.form.refresh_from_db()
        self.assertEqual(self.form.visibility, "restricted")

    def test_inactive_forms_and_archived_organizations_deny_even_invitees(self):
        self.restrict()
        self.client.force_login(self.guest)
        for state in ("draft", "archived"):
            self.form.status = state
            self.form.save()
            self.assertEqual(self.submit().status_code, 404)
        self.form.status = "active"
        self.form.save()
        self.org.is_archived = True
        self.org.save()
        self.assertEqual(self.submit().status_code, 404)

    def test_csrf_enforced_on_session_api_mutations(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        response = client.patch(reverse("forms:api-form-detail", args=(self.form.pk,)), json.dumps({"visibility": "public"}), content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_form_with_records_cannot_be_deleted_through_api(self):
        FormSubmission.objects.create(organization=self.org, form=self.form, data={"note": "keep me"})
        self.client.force_login(self.owner)
        response = self.client.delete(reverse("forms:api-form-detail", args=(self.form.pk,)))
        self.assertEqual(response.status_code, 409)
        self.assertTrue(FormSubmission.objects.exists())

    def test_bad_analytics_form_id_returns_404(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("forms:all-submissions", args=(self.org.slug,)), {"form": "invalid"}).status_code, 404)

    def test_popup_editor_and_responses_use_embedded_layout_and_keep_permissions(self):
        self.client.force_login(self.owner)
        for route in ("forms:form-edit", "forms:submissions"):
            url = reverse(route, args=(self.org.slug, self.form.pk))
            response = self.client.get(url, {"dialog": "1"})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'class="embedded-page"')
            self.assertNotContains(response, 'aria-label="Main navigation"')
            self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")
            self.client.force_login(self.stranger)
            self.assertEqual(self.client.get(url, {"dialog": "1"}).status_code, 403)
            self.client.force_login(self.owner)

    def test_popup_save_persists_and_notifies_parent(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("forms:form-edit", args=(self.org.slug, self.form.pk)) + "?dialog=1", {
            "title": "Saved in popup", "slug": self.form.slug, "schema": json.dumps(self.form.schema),
            "status": "active", "visibility": "organization",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "orgforms:saved")
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")
        self.form.refresh_from_db()
        self.assertEqual(self.form.title, "Saved in popup")

    def test_popup_validation_error_stays_embedded_without_saving(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("forms:form-edit", args=(self.org.slug, self.form.pk)) + "?dialog=1", {
            "title": "Unsaved edit", "slug": self.form.slug, "schema": json.dumps(self.form.schema),
            "visibility": "restricted", "access_emails": "unknown@test.com",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="embedded-page"')
        self.assertContains(response, "must have a unique active OrgForms account")
        self.assertNotContains(response, "orgforms:saved")
        self.form.refresh_from_db()
        self.assertEqual(self.form.title, "Sensitive feedback")

    def test_removed_member_loses_all_workspace_api_access(self):
        self.client.force_login(self.member)
        OrganizationMembership.objects.filter(organization=self.org, user=self.member).delete()
        for url in (
            reverse("organizations:detail", args=(self.org.slug,)),
            reverse("forms:api-forms", args=(self.org.slug,)),
            reverse("organizations:api-documents", args=(self.org.slug,)),
            f"/api/chat/conversations/?organization_slug={self.org.slug}",
        ):
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.submit().status_code, 403)

    def test_document_upload_download_delete_is_persistent_and_protected(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            self.client.force_login(self.owner)
            response = self.client.post(reverse("organizations:api-documents", args=(self.org.slug,)), {
                "file": SimpleUploadedFile("private.txt", b"Private saved document", content_type="text/plain"),
            })
            self.assertEqual(response.status_code, 201)
            document = OrganizationDocument.objects.get(pk=response.json()["id"])
            self.assertEqual(document.organization_id, self.org.pk)
            url = reverse("organizations:api-document-detail", args=(self.org.slug, document.pk))
            self.client.force_login(self.guest)
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.delete(url).status_code, 403)
            self.client.force_login(self.member)
            download = self.client.get(url)
            self.assertEqual(download.status_code, 200)
            self.assertEqual(b"".join(download.streaming_content), b"Private saved document")
            download.close()
            self.assertIn("no-store", download["Cache-Control"])
            self.assertEqual(self.client.delete(url).status_code, 403)
            self.client.force_login(self.owner)
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.client.delete(url).status_code, 204)
            self.assertFalse(OrganizationDocument.objects.filter(pk=document.pk).exists())
            self.assertFalse(document.file.storage.exists(document.file.name))

    def test_new_signup_cannot_claim_existing_unowned_business(self):
        unowned = Organization.objects.create(name="Unclaimed legacy organization")
        Catalog.objects.create(organization=unowned, name=unowned.name)
        response = self.client.post(reverse("accounts:signup"), {
            "email": "new-user@test.com", "password1": "new-account-password123", "password2": "new-account-password123",
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(unowned.memberships.exists())

    def test_local_legacy_claim_preserves_data_and_cannot_replace_an_owner(self):
        unowned = Organization.objects.create(name="Legacy")
        saved_form = DynamicForm.objects.create(organization=unowned, title="Existing records", schema=self.form.schema)
        call_command("claim_legacy_organization", unowned.slug, self.owner.email, stdout=StringIO())
        unowned.refresh_from_db()
        self.assertEqual(unowned.created_by_id, self.owner.pk)
        self.assertTrue(unowned.memberships.filter(user=self.owner, role="admin").exists())
        self.assertTrue(DynamicForm.objects.filter(pk=saved_form.pk).exists())
        with self.assertRaises(CommandError):
            call_command("claim_legacy_organization", unowned.slug, self.stranger.email, stdout=StringIO())

    def test_unrecognized_and_hidden_values_are_not_persisted(self):
        self.client.force_login(self.member)
        response = self.client.post(self.form_url(), json.dumps({"data": {"note": "valid", "organization_id": 999, "order_id": 123}}), content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(FormSubmission.objects.get().data, {"note": "valid"})

    def test_malformed_submission_returns_validation_error(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.form_url(), "[]", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(FormSubmission.objects.exists())

    def test_legacy_session_api_cannot_bypass_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        response = client.patch(reverse("ai_gateway:configuration"), json.dumps({"business_name": "forged"}), content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_unsigned_api_request_cannot_bypass_tenant_membership(self):
        Catalog.objects.create(organization=self.org, name="Private restaurant")
        response = self.client.get(reverse("ai_gateway:configuration"), HTTP_X_ORGANIZATION=self.org.slug)
        self.assertEqual(response.status_code, 403)
