import json
from io import BytesIO
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from organizations.models import Organization, OrganizationMembership
from forms.models import DynamicForm, FormSubmission, Catalog, ItemSelection


@override_settings(OLLAMA_DEFAULT_MODEL='test-model')
class ScopedContextTests(TestCase):
    @patch('chat.views.open_ollama_response', return_value=BytesIO(b'{"message":{"content":"Answer"},"done":true}\n'))
    def test_hidden_and_unlinked_item_records_are_excluded_from_chat(self, upstream):
        user = get_user_model().objects.create_user('member')
        organization = Organization.objects.create(name='Workspace')
        OrganizationMembership.objects.create(organization=organization, user=user, role='member')
        catalog = Catalog.objects.create(organization=organization)
        for visibility, total in [('organization', '10'), ('restricted', '999')]:
            form = DynamicForm.objects.create(organization=organization, title=visibility, visibility=visibility)
            submission = FormSubmission.objects.create(form=form, organization=organization)
            ItemSelection.objects.create(catalog=catalog, submission=submission, total=total)
        ItemSelection.objects.create(catalog=catalog, total='777')
        self.client.force_login(user)
        response = self.client.post('/api/chat/', json.dumps({'organization_slug': organization.slug, 'messages': [{'role': 'user', 'content': 'Summarize'}]}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        b''.join(response.streaming_content)
        context = upstream.call_args.args[1]['messages'][0]['content']
        self.assertIn('"item_selection_count": 1', context)
        self.assertIn('"item_selection_total": "10"', context)
        self.assertNotIn('999', context)
        self.assertNotIn('777', context)
