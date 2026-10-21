import hashlib
import json
import sqlite3
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TransactionTestCase
from accounts.models import UserPortfolio
from ai_gateway.models import AIConfiguration
from forms.models import DynamicForm, FormSubmission, Catalog, CatalogItem, ItemSelection, SelectionLine
from chat.models import ChatConversation, ChatMessage
from django.contrib.auth import get_user_model


class LegacyImportTests(TransactionTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / 'legacy.sqlite3'
        db = sqlite3.connect(self.source)
        db.executescript((Path(__file__).parent / 'fixtures/legacy_schema.sql').read_text())
        timestamp = '2026-10-15 09:00:00'

        def row(table, **values):
            # Populate required fields omitted by this focused historical fixture.
            for _, name, kind, notnull, default, pk in db.execute(f'PRAGMA table_info("{table}")'):
                if name in values or pk or not notnull:
                    continue
                if name.endswith('_at') or name in ('date_joined',): values[name] = timestamp
                elif kind.lower() in ('integer', 'bool', 'decimal', 'real', 'smallint unsigned', 'integer unsigned'): values[name] = 0
                else: values[name] = ''
            columns = ','.join('"'+k+'"' for k in values)
            db.execute(f'INSERT INTO "{table}" ({columns}) VALUES ({",".join("?" for _ in values)})', list(values.values()))
        user = get_user_model()(username='retained')
        user.set_password('retained-password')
        row('auth_user', id=41, username='retained', email='retained@example.test', password=user.password, is_active=1)
        row('organizations_organization', id=12, name='School', slug='school', created_by_id=41, profile_data='{}', business_type='education')
        row('organizations_organizationmembership', id=11, organization_id=12, user_id=41, role='admin')
        row('organizations_userportfolio', id=7, user_id=41, profile_data='{"skill":"teaching"}', use_for_form_assistance=1)
        row('api_businessprofile', id=5, organization_id=12, business_name='School', preferred_provider='cloud', cloud_provider='openai-compatible', default_model='retained-model')
        row('api_menuitem', id=8, business_id=5, name='Book', category='Supplies', price='100.00', is_available=1)
        form_id = '12345678123456781234567812345678'
        row('organizations_dynamicform', id=form_id, organization_id=12, title='Supplies', slug='supplies', status='active', visibility='public', schema=json.dumps({'restaurant_order': True, 'items_field_id': 'items', 'fields': [{'id': 'items', 'label': 'Items', 'type': 'item_cards'}]}))
        row('organizations_formsubmission', id=21, organization_id=12, form_id=form_id, status='submitted', data=json.dumps({'items':[{'menu_item_id':8, 'quantity':2}], 'order_id':31}))
        row('api_order', id=31, business_id=5, status='confirmed', payment_status='paid', total='200.00', subtotal='200.00', fulfillment_status='preparing', review_status='approved')
        row('api_order', id=32, business_id=5, status='pending', payment_status='pending', total='0', fulfillment_status='pending', review_status='pending')
        row('api_orderitem', id=4, order_id=31, menu_item_id=8, quantity=2, unit_price='100', line_total='200')
        conversation_id = '22345678123456781234567812345678'
        row('api_chatconversation', id=conversation_id, owner_hash='retained-hash', organization_id=12, title='Retained conversation')
        row('api_chatmessage', id=6, conversation_id=conversation_id, role='assistant', content='Retained text', images='[]', references='[]', memory_count=0)
        row('django_content_type', id=1, app_label='api', model='businessprofile')
        row('auth_permission', id=1, content_type_id=1, codename='change_businessprofile', name='Can change business profile')
        row('auth_user_user_permissions', id=1, user_id=41, permission_id=1)
        db.commit()
        db.close()

    def test_import_preserves_data_and_remaps_permissions_without_writing_source(self):
        before = hashlib.sha256(self.source.read_bytes()).digest()
        call_command('import_legacy_orgforms', source=str(self.source), stdout=StringIO())
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), before)
        user = get_user_model().objects.get(pk=41)
        self.assertTrue(user.check_password('retained-password'))
        self.assertEqual(user.orgforms_portfolio.profile_data['skill'], 'teaching')
        self.assertTrue(user.has_perm('forms.change_catalog'))
        self.assertTrue(user.has_perm('ai_gateway.change_aiconfiguration'))
        self.assertEqual(AIConfiguration.objects.get(pk=5).default_model, 'retained-model')
        form = DynamicForm.objects.get()
        self.assertEqual(form.schema['fields'][0]['catalog_id'], 5)
        self.assertEqual(FormSubmission.objects.get(pk=21).data['order_id'], 31)
        selection = ItemSelection.objects.get(pk=31)
        self.assertEqual(selection.submission_id, 21)
        self.assertEqual(selection.field_id, 'items')
        self.assertEqual(selection.status, 'confirmed')
        self.assertEqual(selection.payment_status, 'paid')
        self.assertIsNone(ItemSelection.objects.get(pk=32).submission_id)
        self.assertEqual(SelectionLine.objects.get(pk=4).name, 'Book')
        self.assertEqual(ChatMessage.objects.get(pk=6).content, 'Retained text')
        self.assertFalse(connection.cursor().execute("SELECT name FROM sqlite_master WHERE name LIKE 'restaurant_%'").fetchall())
        with self.assertRaises(CommandError):
            call_command('import_legacy_orgforms', source=str(self.source), stdout=StringIO())

    def test_invalid_import_rolls_back_all_changes(self):
        db = sqlite3.connect(self.source)
        db.execute("UPDATE api_orderitem SET menu_item_id=999")
        db.commit()
        db.close()
        with self.assertRaises(CommandError):
            call_command('import_legacy_orgforms', source=str(self.source), stdout=StringIO())
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Catalog.objects.exists())

    def test_failure_after_copy_rolls_back_imported_rows(self):
        from unittest.mock import patch
        with patch('organizations.management.commands.import_legacy_orgforms.Command._permissions', side_effect=CommandError('Simulated permission failure')):
            with self.assertRaises(CommandError):
                call_command('import_legacy_orgforms', source=str(self.source), stdout=StringIO())
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Catalog.objects.exists())
        self.assertFalse(ChatConversation.objects.exists())
