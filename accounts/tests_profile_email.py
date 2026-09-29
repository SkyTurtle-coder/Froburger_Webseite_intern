from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .auth_backends import EmailOrVulgoBackend
from .forms import AdminProfileForm
from .models import Role


class ProfileEmailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member = User.objects.create_user(
            username="email-member", email="old@example.com", password="testpass123"
        )
        cls.admin = User.objects.create_user(
            username="email-admin", email="admin@example.com", password="testpass123"
        )
        cls.admin.profile.roles.add(Role.objects.get(code="ADMIN"))

    def setUp(self):
        self.url = reverse("profile-edit", kwargs={"pk": self.member.profile.pk})
        self.client.force_login(self.member)

    def payload(self, email):
        return {"first_name": "Anna", "last_name": "Muster", "email": email}

    def test_current_email_is_displayed(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'name="email"')
        self.assertContains(response, 'value="old@example.com"')

    def test_member_can_change_email_and_log_in_with_new_address(self):
        response = self.client.post(self.url, self.payload(" New@Example.com "))
        self.assertRedirects(response, reverse("profile-detail", kwargs={"pk": self.member.profile.pk}))
        self.member.refresh_from_db()
        self.assertEqual(self.member.email, "new@example.com")
        backend = EmailOrVulgoBackend()
        self.assertEqual(backend.authenticate(None, username="new@example.com", password="testpass123"), self.member)
        self.assertIsNone(backend.authenticate(None, username="old@example.com", password="testpass123"))

    def test_admin_can_change_member_email(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, self.payload("changed@example.com"))
        self.assertEqual(response.status_code, 302)
        self.member.refresh_from_db()
        self.admin.refresh_from_db()
        self.assertEqual(self.member.email, "changed@example.com")
        self.assertEqual(self.admin.email, "admin@example.com")

    def test_unchanged_email_is_accepted(self):
        response = self.client.post(self.url, self.payload("old@example.com"))
        self.assertEqual(response.status_code, 302)

    def test_invalid_empty_and_duplicate_email_do_not_change_profile(self):
        for email in ("", "invalid", "ADMIN@EXAMPLE.COM"):
            with self.subTest(email=email):
                response = self.client.post(self.url, self.payload(email))
                self.assertEqual(response.status_code, 200)
                self.assertIn("email", response.context["form"].errors)
                self.member.refresh_from_db()
                self.member.profile.refresh_from_db()
                self.assertEqual(self.member.email, "old@example.com")
                self.assertNotEqual(self.member.profile.first_name, "Anna")

    def test_member_cannot_edit_another_account(self):
        response = self.client.post(
            reverse("profile-edit", kwargs={"pk": self.admin.profile.pk}),
            self.payload("takeover@example.com"),
        )
        self.assertEqual(response.status_code, 302)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.email, "admin@example.com")

    def test_deferred_save_used_by_django_admin(self):
        form = AdminProfileForm(self.payload("deferred@example.com"), instance=self.member.profile)
        self.assertTrue(form.is_valid(), form.errors)
        profile = form.save(commit=False)
        self.member.refresh_from_db()
        self.assertEqual(self.member.email, "old@example.com")
        profile.save()
        form.save_m2m()
        self.member.refresh_from_db()
        self.assertEqual(self.member.email, "deferred@example.com")
