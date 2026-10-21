"""Import the pre-five-app SQLite schema into a freshly migrated database."""
import json
import sqlite3
from datetime import datetime, date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

# Source model names are deliberately confined to this one-time transition tool.
TABLES = {
    'auth_user': 'auth_user',
    'auth_group': 'auth_group',
    'auth_user_groups': 'auth_user_groups',
    'django_session': 'django_session',
    'organizations_organization': 'organizations_organization',
    'organizations_organizationmembership': 'organizations_organizationmembership',
    'organizations_organizationdocument': 'organizations_organizationdocument',
    'organizations_organizationgroup': 'organizations_organizationgroup',
    'organizations_organizationgroup_members': 'organizations_organizationgroup_members',
    'accounts_userportfolio': 'organizations_userportfolio',
    'accounts_personaldocument': 'organizations_personaldocument',
    'ai_gateway_aiconfiguration': 'api_businessprofile',
    'ai_gateway_localmodelprofile': 'api_localmodelprofile',
    'forms_catalog': 'api_businessprofile',
    'forms_catalogitem': 'api_menuitem',
    'forms_dynamicform': 'organizations_dynamicform',
    'forms_dynamicform_allowed_users': 'organizations_dynamicform_allowed_users',
    'forms_dynamicform_allowed_groups': 'organizations_dynamicform_allowed_groups',
    'forms_dynamicform_editors': 'organizations_dynamicform_editors',
    'forms_formsubmission': 'organizations_formsubmission',
    'forms_submissionattachment': 'organizations_submissionattachment',
    'forms_itemselection': 'api_order',
    'forms_selectionline': 'api_orderitem',
    'chat_chatconversation': 'api_chatconversation',
    'chat_chatmessage': 'api_chatmessage',
    'chat_chatmemory': 'api_chatmemory',
    'chat_chatmemorypreference': 'api_chatmemorypreference',
}
MODEL_MAP = {
    ('api', 'businessprofile'): [('ai_gateway', 'aiconfiguration'), ('forms', 'catalog')],
    ('api', 'localmodelprofile'): [('ai_gateway', 'localmodelprofile')],
    **{('api', name): [('chat', name)] for name in ('chatconversation', 'chatmessage', 'chatmemory', 'chatmemorypreference')},
    ('api', 'menuitem'): [('forms', 'catalogitem')],
    ('api', 'order'): [('forms', 'itemselection')],
    ('api', 'orderitem'): [('forms', 'selectionline')],
    **{('organizations', name): [('accounts', name)] for name in ('userportfolio', 'personaldocument')},
    **{('organizations', name): [('forms', name)] for name in ('dynamicform', 'formsubmission', 'submissionattachment')},
}


class Command(BaseCommand):
    help = 'Read a legacy SQLite backup and import it into an empty, migrated OrgForms database. Never changes the source.'

    def add_arguments(self, parser):
        parser.add_argument('--source', required=True)

    def handle(self, *args, **options):
        source_path = Path(options['source']).resolve()
        destination = Path(connection.settings_dict['NAME']).resolve()
        if not source_path.is_file() or source_path == destination:
            raise CommandError('Choose an existing source database different from the destination.')
        source = sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True)
        source.row_factory = sqlite3.Row
        connection.ensure_connection()
        target = connection.connection
        try:
            source.execute('BEGIN')  # Consistent source snapshot, including WAL commits.
            if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise CommandError('The source database failed its integrity check.')
            if source.execute('PRAGMA foreign_key_check').fetchall():
                raise CommandError('The source database has broken foreign keys.')
            for table in TABLES:
                if target.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]:
                    raise CommandError(f'{table} is not empty. Import into a fresh database.')
            tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required = set(TABLES.values())
            if required - tables:
                raise CommandError(f'Source schema is missing tables: {sorted(required - tables)}')
            catalogs = {r['organization_id']: r['id'] for r in source.execute('SELECT * FROM api_businessprofile') if r['organization_id'] is not None}
            forms = {r['id']: dict(r) for r in source.execute('SELECT * FROM organizations_dynamicform')}
            links = {}
            for row in source.execute('SELECT * FROM organizations_formsubmission'):
                order_id = json.loads(row['data']).get('order_id')
                if order_id:
                    if order_id in links:
                        raise CommandError(f'Order {order_id} is linked to multiple submissions; resolve this before importing.')
                    form = forms[row['form_id']]
                    schema = json.loads(form['schema'])
                    links[order_id] = (row['id'], schema.get('items_field_id', 'items'))
            names = {r['id']: r['name'] for r in source.execute('SELECT id, name FROM api_menuitem')}
            target.execute('BEGIN')
            target.execute('PRAGMA defer_foreign_keys=ON')
            counts = {}
            for table, old_table in TABLES.items():
                rows = list(source.execute(f'SELECT * FROM "{old_table}"'))
                columns = [r[1] for r in target.execute(f'PRAGMA table_info("{table}")')]
                for row in rows:
                    values = dict(row)
                    if table == 'forms_catalog':
                        values['name'] = values['business_name']
                    if table in ('forms_catalogitem', 'forms_itemselection'):
                        values['catalog_id'] = values['business_id']
                    if table == 'forms_selectionline':
                        values.update(selection_id=values['order_id'], catalog_item_id=values['menu_item_id'], name=names[values['menu_item_id']])
                    if table == 'forms_itemselection':
                        values['submission_id'], values['field_id'] = links.get(values['id'], (None, ''))
                    if table == 'forms_dynamicform':
                        schema = json.loads(values['schema'])
                        for field in schema.get('fields', []):
                            if field.get('type') == 'item_cards':
                                catalog_id = field.get('catalog_id') or catalogs.get(values['organization_id'])
                                if not catalog_id:
                                    # A reusable field may legitimately have an empty catalog.
                                    catalog_id = target.execute('INSERT INTO forms_catalog (organization_id,name,description,discount_percent,tax_rate,created_at,updated_at) VALUES (?,?,?,0,0,?,?)', (values['organization_id'], 'Items', '', values['created_at'], values['updated_at'])).lastrowid
                                    catalogs[values['organization_id']] = catalog_id
                                field['catalog_id'] = catalog_id
                        values['schema'] = json.dumps(schema)
                    missing = set(columns) - values.keys()
                    if missing:
                        raise CommandError(f'Missing import fields in {table}: {missing}')
                    target.execute(f'INSERT INTO "{table}" ({",".join(chr(34)+c+chr(34) for c in columns)}) VALUES ({",".join("?" for _ in columns)})', [values[c] for c in columns])
                counts[table] = len(rows)
            self._permissions(source, target)
            # Verify exact copied values, except intentional schema/field transformations.
            for table, count in counts.items():
                if table != 'forms_catalog' and target.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] != count:
                    raise CommandError(f'Count mismatch: {table}')
                old_table = TABLES[table]
                old_columns = {r[1] for r in source.execute(f'PRAGMA table_info("{old_table}")')}
                new_columns = {r[1] for r in target.execute(f'PRAGMA table_info("{table}")')}
                common = sorted(old_columns & new_columns - ({'schema'} if table == 'forms_dynamicform' else set()))
                if common:
                    select = ','.join('"'+c+'"' for c in common)
                    expected = sorted([tuple(r) for r in source.execute(f'SELECT {select} FROM "{old_table}"')], key=repr)
                    actual = sorted([tuple(v.isoformat(sep=' ') if isinstance(v, datetime) else v.isoformat() if isinstance(v, date) else v for v in r) for r in target.execute(f'SELECT {select} FROM "{table}"')], key=repr)
                    if table == 'forms_catalog':
                        actual = [row for row in actual if row[common.index('id')] in {r[0] for r in source.execute('SELECT id FROM api_businessprofile')}]
                    if actual != expected:
                        raise CommandError(f'Value mismatch: {table}')
            if target.execute('PRAGMA foreign_key_check').fetchall() or target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise CommandError('Imported database failed integrity checks.')
            target.commit()
            self.stdout.write(self.style.SUCCESS('Imported and verified all retained records. Source database unchanged.'))
            self.stdout.write(json.dumps(counts, indent=2))
        except Exception:
            target.rollback()
            raise
        finally:
            source.close()

    def _permissions(self, source, target):
        types = {r[0]: (r[1], r[2]) for r in source.execute('SELECT id,app_label,model FROM django_content_type')}
        remap = {}
        for row in source.execute('SELECT * FROM auth_permission'):
            old_app, old_model = types[row['content_type_id']]
            destinations = MODEL_MAP.get((old_app, old_model), [] if old_app in ('api', 'restaurant', 'org') else [(old_app, old_model)])
            mapped = []
            for app, model in destinations:
                ct = target.execute('SELECT id FROM django_content_type WHERE app_label=? AND model=?', (app, model)).fetchone()
                if ct is None:
                    continue
                code = row['codename']
                if code.endswith('_' + old_model):
                    code = code[:-len(old_model)] + model
                permission = target.execute('SELECT id FROM auth_permission WHERE content_type_id=? AND codename=?', (ct[0], code)).fetchone()
                if permission is None:
                    permission_id = target.execute('INSERT INTO auth_permission (name,content_type_id,codename) VALUES (?,?,?)', (row['name'], ct[0], code)).lastrowid
                else:
                    permission_id = permission[0]
                mapped.append(permission_id)
            remap[row['id']] = mapped
        for table, column in [('auth_user_user_permissions', 'user_id'), ('auth_group_permissions', 'group_id')]:
            for row in source.execute(f'SELECT * FROM {table}'):
                for permission in remap[row['permission_id']]:
                    target.execute(f'INSERT OR IGNORE INTO {table} ({column},permission_id) VALUES (?,?)', (row[column], permission))
