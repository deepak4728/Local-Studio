import json
from io import BytesIO
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from .models import AIConfiguration, LocalModelProfile
from organizations.models import Organization, OrganizationMembership
from forms.models import Catalog


class AIConfigurationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('owner', password='test-password')
        self.organization = Organization.objects.create(name='General office')
        OrganizationMembership.objects.create(organization=self.organization, user=self.user, role='admin')
        self.client.force_login(self.user)

    def test_ai_settings_are_independent_of_catalogs(self):
        response = self.client.patch(reverse('ai_gateway:configuration'), json.dumps({'default_model': 'office-model'}), content_type='application/json', HTTP_X_ORGANIZATION=self.organization.slug)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.organization.ai_configuration.default_model, 'office-model')
        self.assertFalse(Catalog.objects.exists())

    def test_member_can_read_but_cannot_change_ai_settings(self):
        membership = self.organization.memberships.get()
        membership.role = 'member'
        membership.save()
        url = reverse('ai_gateway:configuration')
        self.assertEqual(self.client.get(url, HTTP_X_ORGANIZATION=self.organization.slug).status_code, 200)
        self.assertEqual(self.client.patch(url, '{}', content_type='application/json', HTTP_X_ORGANIZATION=self.organization.slug).status_code, 403)

    def test_shared_model_profiles_require_installation_admin(self):
        url = reverse('ai_gateway:local-model-profiles')
        self.assertEqual(self.client.post(url, {'name': 'model'}).status_code, 403)
        self.user.is_superuser = True
        self.user.save()
        self.assertEqual(self.client.post(url, {'name': 'model'}).status_code, 201)
        self.assertTrue(LocalModelProfile.objects.filter(name='model').exists())

    @override_settings(CLOUD_API_KEY='test-key', CLOUD_API_BASE_URL='https://cloud.example/v1', OLLAMA_DEFAULT_MODEL='test')
    @patch('ai_gateway.providers.urlopen', return_value=BytesIO(b'{"choices": []}'))
    def test_invalid_cloud_response_returns_clear_error(self, upstream):
        AIConfiguration.objects.create(organization=self.organization, preferred_provider='cloud', cloud_provider='openai-compatible', default_model='test')
        response = self.client.post('/api/chat/', json.dumps({'organization_slug': self.organization.slug, 'messages': [{'role': 'user', 'content': 'Hello'}]}), content_type='application/json')
        self.assertEqual(response.status_code, 502)
