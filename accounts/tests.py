from tempfile import TemporaryDirectory
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from .models import PersonalDocument, UserPortfolio


class AccountPrivacyTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        settings = override_settings(MEDIA_ROOT=self.directory.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.user = get_user_model().objects.create_user('owner', password='test-password')
        self.other = get_user_model().objects.create_user('other')

    def test_profile_requires_login_and_portfolio_assistance_requires_opt_in(self):
        self.assertEqual(self.client.get(reverse('accounts:profile')).status_code, 302)
        self.client.force_login(self.user)
        portfolio = UserPortfolio.objects.create(user=self.user, profile_data={'skills': ['Python']})
        url = reverse('accounts:personal-portfolio')
        self.assertFalse(self.client.get(url).json()['enabled'])
        portfolio.use_for_form_assistance = True
        portfolio.save()
        self.assertEqual(self.client.get(url).json()['profile_data']['skills'], ['Python'])

    def test_uploaded_personal_document_remains_private(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('accounts:profile'), {'action':'upload-document', 'kind':'resume', 'title':'CV', 'file':SimpleUploadedFile('cv.pdf', b'%PDF-private', content_type='application/pdf')})
        self.assertEqual(response.status_code, 302)
        document = PersonalDocument.objects.get()
        url = reverse('accounts:personal-document', args=[document.pk])
        download = self.client.get(url)
        self.assertEqual(b''.join(download.streaming_content), b'%PDF-private')
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
