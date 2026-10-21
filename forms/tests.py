import json
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from .models import Catalog, CatalogItem, DynamicForm, FormSubmission, ItemSelection, SelectionLine
from organizations.models import Organization, OrganizationMembership


class ReusableItemFieldTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('teacher', password='test-password')
        self.organization = Organization.objects.create(name='School', business_type='education', created_by=self.user)
        OrganizationMembership.objects.create(organization=self.organization, user=self.user, role='admin')
        self.catalog = Catalog.objects.create(organization=self.organization, name='Supplies', discount_percent='10', tax_rate='5')
        self.item = CatalogItem.objects.create(catalog=self.catalog, name='Notebook', price='100')
        self.form = DynamicForm.objects.create(organization=self.organization, title='Supplies', status='active', visibility='public', schema={'fields': [{'id': 'supplies', 'label': 'Supplies', 'type': 'item_cards', 'required': True}]})
        self.url = reverse('forms:public-form', args=[self.organization.slug, self.form.slug])

    def submit(self, items=None, **extra):
        return self.client.post(self.url, json.dumps({'data': {'supplies': items if items is not None else [{'menu_item_id': self.item.pk, 'quantity': 2, 'price': '0.01'}]}, **extra}), content_type='application/json')

    def test_non_restaurant_field_creates_authoritative_snapshot(self):
        response = self.submit()
        self.assertEqual(response.status_code, 201)
        selection = ItemSelection.objects.get()
        self.assertEqual(selection.submission_id, response.json()['submission_id'])
        self.assertEqual(selection.field_id, 'supplies')
        self.assertEqual(selection.subtotal, Decimal('200'))
        self.assertEqual(selection.discount, Decimal('20'))
        self.assertEqual(selection.tax, Decimal('10'))
        self.assertEqual(selection.total, Decimal('190'))
        line = SelectionLine.objects.get()
        self.assertEqual(line.unit_price, Decimal('100'))
        self.assertEqual(line.name, 'Notebook')
        self.item.name = 'Renamed'
        self.item.price = '999'
        self.item.save()
        line.refresh_from_db()
        self.assertEqual(line.name, 'Notebook')
        self.assertEqual(line.unit_price, Decimal('100'))

    def test_unavailable_or_foreign_items_rejected_without_partial_submission(self):
        other = Organization.objects.create(name='Other')
        foreign = CatalogItem.objects.create(catalog=Catalog.objects.create(organization=other), name='Private', price='50')
        self.assertEqual(self.submit([{'menu_item_id': foreign.pk, 'quantity': 1}]).status_code, 400)
        self.item.is_available = False
        self.item.save()
        self.assertEqual(self.submit().status_code, 400)
        self.assertFalse(FormSubmission.objects.exists())
        self.assertFalse(ItemSelection.objects.exists())

    def test_catalog_binding_cannot_cross_organization_boundary(self):
        other = Organization.objects.create(name='Other')
        catalog = Catalog.objects.create(organization=other)
        self.form.schema['fields'][0]['catalog_id'] = catalog.pk
        with self.assertRaises(ValidationError):
            self.form.save()

    def test_invalid_quantities_are_rejected(self):
        for quantity in [0, -1, 51, 1.5, True, '1.2']:
            with self.subTest(quantity=quantity):
                self.assertEqual(self.submit([{'menu_item_id': self.item.pk, 'quantity': quantity}]).status_code, 400)
        self.assertFalse(FormSubmission.objects.exists())

    def test_multiple_fields_use_their_bound_catalogs(self):
        second = Catalog.objects.create(organization=self.organization, name='Activities')
        ticket = CatalogItem.objects.create(catalog=second, name='Trip', price='25')
        self.form.schema['fields'].append({'id': 'trip', 'label': 'Trip', 'type': 'item_cards', 'catalog_id': second.pk})
        self.form.save()
        response = self.client.post(self.url, json.dumps({'data': {'supplies': [{'catalog_item_id': self.item.pk, 'quantity': 1}], 'trip': [{'catalog_item_id': ticket.pk, 'quantity': 3}]}}), content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(ItemSelection.objects.values_list('field_id', flat=True)), {'supplies', 'trip'})
        self.assertContains(self.client.get(self.url), 'field-catalogs')
        wrong = self.client.post(self.url, json.dumps({'data': {'supplies': [{'menu_item_id': ticket.pk, 'quantity': 1}]}}), content_type='application/json')
        self.assertEqual(wrong.status_code, 400)

    def test_response_edit_updates_existing_selection_and_rejects_processing(self):
        first = self.submit().json()
        updated = self.submit([{'menu_item_id': self.item.pk, 'quantity': 3}], edit_token=first['edit_token'])
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(ItemSelection.objects.count(), 1)
        self.assertEqual(SelectionLine.objects.get().quantity, 3)
        selection = ItemSelection.objects.get()
        selection.status = ItemSelection.STATUS_CONFIRMED
        selection.save()
        self.assertEqual(self.submit(edit_token=first['edit_token']).status_code, 400)
        self.assertEqual(SelectionLine.objects.get().quantity, 3)

    def test_respondent_cannot_attach_someone_elses_historical_order(self):
        old = ItemSelection.objects.create(catalog=self.catalog, customer_name='Private history')
        response = self.submit(order_id=old.pk)
        self.assertEqual(response.status_code, 201)
        old.refresh_from_db()
        self.assertIsNone(old.submission_id)
        self.assertEqual(ItemSelection.objects.count(), 2)

    def test_catalog_manager_works_for_general_organizations(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('forms:menu', args=[self.organization.slug]), {'name': 'Pencil', 'price': '5'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(CatalogItem.objects.filter(catalog=self.catalog, name='Pencil').exists())

    def test_foreign_catalog_rejected_by_form_api(self):
        self.client.force_login(self.user)
        foreign = Catalog.objects.create(organization=Organization.objects.create(name='Private'))
        response = self.client.post(reverse('forms:api-forms', args=[self.organization.slug]), json.dumps({'title': 'Invalid', 'schema': {'fields': [{'id': 'items', 'label': 'Items', 'type': 'item_cards', 'catalog_id': foreign.pk}]}}), content_type='application/json')
        self.assertEqual(response.status_code, 400)
