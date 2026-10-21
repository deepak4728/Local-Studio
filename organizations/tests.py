import json
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from forms.models import Catalog, CatalogItem
from chat.models import ChatConversation
from forms.models import DynamicForm, FormSubmission
from organizations.models import Organization, OrganizationDocument, OrganizationMembership
from ai_gateway.classification import classify_text
from .services import retrieve_document_snippets


class OrganizationFormTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner@example.com", email="owner@example.com", password="test-pass-123")
        self.other = User.objects.create_user(username="other@example.com", email="other@example.com", password="test-pass-123")
        self.org = Organization.objects.create(name="Jaipur Cafe", business_type=Organization.TYPE_CAFE, created_by=self.owner)
        self.other_org = Organization.objects.create(name="Other Cafe", business_type=Organization.TYPE_CAFE, created_by=self.other)
        OrganizationMembership.objects.create(organization=self.org, user=self.owner, role=OrganizationMembership.ROLE_ADMIN)
        OrganizationMembership.objects.create(organization=self.other_org, user=self.other, role=OrganizationMembership.ROLE_ADMIN)
        self.form = DynamicForm.objects.create(
            organization=self.org,
            title="Feedback",
            slug="feedback",
            status=DynamicForm.STATUS_ACTIVE,
            visibility=DynamicForm.VISIBILITY_PUBLIC,
            schema={"fields": [
                {"id": "email", "label": "Email", "type": "email", "required": True},
                {"id": "phone", "label": "Mobile number", "type": "tel", "required": False},
            ]},
        )

    def test_public_form_submission_validates_and_saves(self):
        url = reverse("forms:public-form", args=(self.org.slug, self.form.slug))
        response = self.client.post(
            url,
            data=json.dumps({"data": {"email": "not-an-email", "phone": "+919876543210"}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(FormSubmission.objects.count(), 0)

        response = self.client.post(
            url,
            data=json.dumps({"data": {"email": "guest@example.com", "phone": "+919876543210"}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(FormSubmission.objects.get().organization, self.org)

    def test_public_classifier_suggests_values_for_active_form(self):
        response = self.client.post(
            reverse("forms:api-public-classify", args=(self.form.pk,)),
            data=json.dumps({"text": "name Rahul, email rahul@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        classifications = response.json()["classifications"]
        self.assertTrue(classifications)
        self.assertTrue(all("probability" in item and "predictedFieldId" in item for item in classifications))

    def test_draft_and_archived_forms_are_not_public(self):
        for form_status in (DynamicForm.STATUS_DRAFT, DynamicForm.STATUS_ARCHIVED):
            self.form.status = form_status
            self.form.save(update_fields=("status",))
            response = self.client.get(reverse("forms:public-form", args=(self.org.slug, self.form.slug)))
            self.assertEqual(response.status_code, 404)

    def test_organization_page_requires_membership(self):
        url = reverse("organizations:detail", args=(self.org.slug,))
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_field_library_editor_is_available_to_organization_admin(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("forms:form-new", args=(self.org.slug,)))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email address")
        self.assertContains(response, "Mobile number")
        self.assertContains(response, "Item cards")

    def test_admin_can_assign_organization_roles(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("organizations:detail", args=(self.org.slug,)),
            {"email": self.other.email, "role": OrganizationMembership.ROLE_MANAGER},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            OrganizationMembership.objects.get(organization=self.org, user=self.other).role,
            OrganizationMembership.ROLE_MANAGER,
        )

    def test_chat_history_and_document_retrieval_are_organization_scoped(self):
        owner_hash = ChatConversation.hash_owner(f"orgforms:{self.owner.pk}:{self.org.pk}")
        conversation = ChatConversation.objects.create(
            organization=self.org, owner_hash=owner_hash, title="Cafe feedback insights",
        )
        ChatConversation.objects.create(
            organization=self.other_org,
            owner_hash=ChatConversation.hash_owner(f"orgforms:{self.owner.pk}:{self.other_org.pk}"),
            title="Other business chat",
        )
        OrganizationDocument.objects.create(
            organization=self.org, title="Menu", file="menu.txt", extracted_text="Dal Baati Churma is a local specialty.",
        )
        OrganizationDocument.objects.create(
            organization=self.other_org, title="Private", file="private.txt", extracted_text="Private recipe details.",
        )
        self.client.force_login(self.owner)
        response = self.client.get(f"/api/chat/conversations/?organization_slug={self.org.slug}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], [str(conversation.pk)])
        snippets = retrieve_document_snippets(self.org, "local specialty")
        self.assertEqual([item["title"] for item in snippets], ["Menu"])

    def test_members_cannot_read_another_organizations_submissions(self):
        submission = FormSubmission.objects.create(
            organization=self.org, form=self.form, data={"email": "guest@example.com"},
        )
        self.client.force_login(self.other)
        response = self.client.get(reverse("forms:api-submissions", args=(self.form.pk,)))
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, submission.data["email"], status_code=403)

    def test_classifier_returns_editable_confidence_assignments(self):
        result = classify_text("guest@example.com", [
            {"id": "email", "label": "Email address", "type": "email"},
            {"id": "phone", "label": "Mobile number", "type": "tel"},
        ])
        self.assertEqual(result["classifications"][0]["predictedFieldId"], "email")
        self.assertGreater(result["classifications"][0]["probability"], 0)

    def test_local_classifier_uses_typed_matchers_and_softmax_probabilities(self):
        fields = [
            {"id": "visit_date", "label": "Visit date", "type": "date"},
            {"id": "rating", "label": "Experience rating", "type": "rating"},
            {"id": "service", "label": "Service type", "type": "select", "options": ["Dine in", "Takeaway"]},
            {"id": "notes", "label": "Additional notes", "type": "textarea"},
        ]
        cases = (("2026-10-15", "visit_date"), ("5 stars", "rating"), ("Takeaway", "service"),
                 ("The staff were kind and the food arrived quickly.", "notes"))
        for text, expected_field in cases:
            with self.subTest(text=text):
                result = classify_text(text, fields)["classifications"][0]
                self.assertEqual(result["predictedFieldId"], expected_field)
                self.assertAlmostEqual(sum(item["probability"] for item in result["distribution"]), 1.0, places=3)

    def test_public_quick_fill_uses_local_classifier(self):
        response = self.client.post(
            reverse("forms:api-public-classify", args=(self.form.pk,)),
            data=json.dumps({"text": "rahul@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model"], "local-rules-v1")

    def test_legacy_item_card_form_creates_an_owned_selection(self):
        business = Catalog.objects.create(
            organization=self.org,
            name=self.org.name,
        )
        menu = CatalogItem.objects.create(catalog=business, name="Dal Baati Churma", price="250.00", is_available=True)
        order_form = DynamicForm.objects.create(
            organization=self.org, title="ItemSelection", slug="order", status=DynamicForm.STATUS_ACTIVE, visibility="public",
            schema={"restaurant_order": True, "items_field_id": "items", "fields": [
                {"id": "items", "label": "Menu items", "type": "item_cards", "required": True},
            ]},
        )
        response = self.client.post(
            reverse("forms:public-form", args=(self.org.slug, order_form.slug)),
            data=json.dumps({"respondent_name": "Guest", "data": {"items": [{"menu_item_id": menu.pk, "quantity": 3}]}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        from forms.models import ItemSelection, SelectionLine
        order = ItemSelection.objects.get(catalog=business)
        self.assertEqual(order.customer_name, "Guest")
        self.assertEqual(SelectionLine.objects.get(selection=order).quantity, 3)

    def test_menu_api_only_returns_the_selected_organizations_items(self):
        own_business = Catalog.objects.create(
            organization=self.org, name=self.org.name,
        )
        other_business = Catalog.objects.create(
            organization=self.other_org, name=self.other_org.name,
        )
        CatalogItem.objects.create(catalog=own_business, name="Dal Baati", price="250.00")
        CatalogItem.objects.create(catalog=other_business, name="Private Thali", price="350.00")
        self.client.force_login(self.owner)
        response = self.client.get(reverse("forms:menu-items"), HTTP_X_ORGANIZATION=self.org.slug)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dal Baati")
        self.assertNotContains(response, "Private Thali")

    def test_admin_can_manage_their_organization_menu(self):
        business = Catalog.objects.create(
            organization=self.org, name=self.org.name,
        )
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("forms:menu", args=(self.org.slug,)),
            {"name": "Dal Baati Churma", "category": "Rajasthani", "price": "250.00"},
        )
        self.assertEqual(response.status_code, 302)
        item = CatalogItem.objects.get(name="Dal Baati Churma")
        self.assertEqual(item.catalog, business)

    def test_retired_order_status_endpoint_cannot_change_records(self):
        from forms.models import ItemSelection
        business = Catalog.objects.create(
            organization=self.org, name=self.org.name,
        )
        Catalog.objects.create(
            organization=self.other_org, name=self.other_org.name,
        )
        order = ItemSelection.objects.create(catalog=business, customer_name="Private guest")
        self.client.force_login(self.other)
        response = self.client.patch(
            f"/api/orders/{order.pk}/status/",
            data=json.dumps({"status": "cancelled"}),
            content_type="application/json",
            HTTP_X_ORGANIZATION=self.other_org.slug,
        )
        self.assertEqual(response.status_code, 404)
