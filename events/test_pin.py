import json
from datetime import timedelta

from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from . import signing
from .models import Event, EventSignup, EventSignupColumn, SignupAuditLog


@override_settings(PUBLIC_EVENT_SIGNUP_SHARED_SECRET="pin-tests")
class SignupPinTests(TestCase):
    def setUp(self):
        cache.clear()
        start = timezone.now() + timedelta(days=3)
        self.event = Event.objects.create(title="PIN Test", short_description="Test", location="Basel",
                                          start=start, end=start + timedelta(hours=2), status="OFF", is_public=True)
        self.column = EventSignupColumn.objects.create(event=self.event, label="Menü", field_type="text")
        self.signup = EventSignup(event=self.event, vulgo="Newton", attending=True,
                                  values={self.column.key: "Vegi", "inactive": "retain"})
        self.signup.set_pin("01234")
        self.signup.save()
        self.counter = 0

    def post(self, **payload):
        # Different timestamps keep repeated credential tests independent of replay protection.
        self.counter += 1
        timestamp = str(int(timezone.now().timestamp()) + self.counter)
        body = json.dumps(payload).encode()
        signature = signing.compute_signature("pin-tests", self.event.slug, timestamp, body)
        return self.client.post(reverse("api-v1-event-signup", kwargs={"slug": self.event.slug}),
                                data=body, content_type="application/json",
                                HTTP_X_AVF_TIMESTAMP=timestamp, HTTP_X_AVF_SIGNATURE=signature)

    def test_create_pin_validation_and_hashing(self):
        for pin in ("0123", "01234", "012345"):
            cache.clear()
            response = self.post(vulgo="Test" + pin, attending=True, values={}, pin=pin)
            self.assertEqual(response.status_code, 201)
            signup = EventSignup.objects.get(vulgo="Test" + pin)
            self.assertNotEqual(signup.pin_hash, pin)
            self.assertTrue(check_password(pin, signup.pin_hash))
        for pin in (None, "", "123", "1234567", "12ab", "１２３４", 1234, ["1234"], "1234\n"):
            cache.clear()
            response = self.post(vulgo="Invalid", attending=True, values={}, pin=pin)
            self.assertEqual(response.status_code, 400)

    def test_read_and_update_preserve_identity_and_inactive_data(self):
        response = self.post(operation="read", vulgo=" newton ", pin="01234")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertNotIn("pin", response.content.decode())
        self.assertNotIn("inactive", response.json()["signup"]["values"])
        response = self.post(operation="update", vulgo="Newton", pin="01234", attending=False,
                             values={self.column.key: "Fleisch"})
        self.assertEqual(response.status_code, 200)
        self.signup.refresh_from_db()
        self.assertFalse(self.signup.attending)
        self.assertEqual(self.signup.values, {self.column.key: "Fleisch", "inactive": "retain"})
        self.assertEqual(EventSignup.objects.count(), 1)
        self.assertTrue(SignupAuditLog.objects.filter(signup_id=self.signup.pk, action="updated").exists())

    def test_wrong_credentials_and_tampering(self):
        for extra in ({"vulgo": "Other"}, {"pin": "9999"}, {"signup_id": self.signup.pk}, {"pin": []}):
            response = self.post(**{"operation": "read", "vulgo": "Newton", "pin": "01234", **extra})
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("signup", response.json())
        response = self.post(operation="update", vulgo="Newton", pin="9999", attending=False, values={})
        self.assertEqual(response.status_code, 403)
        self.signup.refresh_from_db()
        self.assertTrue(self.signup.attending)

    def test_lock_persists_without_cache_and_expires(self):
        for attempt in range(5):
            self.assertEqual(self.post(operation="read", vulgo="Newton", pin="9999").status_code, 403)
        cache.clear()
        self.assertEqual(self.post(operation="read", vulgo="Newton", pin="01234").status_code, 429)
        EventSignup.objects.filter(pk=self.signup.pk).update(pin_locked_until=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.post(operation="read", vulgo="Newton", pin="01234").status_code, 200)
        self.signup.refresh_from_db()
        self.assertEqual(self.signup.pin_failed_attempts, 0)

    def test_legacy_deleted_closed_and_disabled(self):
        self.signup.pin_hash = ""
        self.signup.save()
        self.assertEqual(self.post(operation="read", vulgo="Newton", pin="01234").status_code, 403)
        self.signup.set_pin("01234")
        self.signup.save()
        self.event.signup_deadline_at = timezone.now() - timedelta(seconds=1)
        self.event.save()
        for operation in ("read", "update"):
            self.assertEqual(self.post(operation=operation, vulgo="Newton", pin="01234").status_code, 409)
        self.event.signup_deadline_at = timezone.now() + timedelta(days=1)
        self.event.signup_enabled = False
        self.event.save()
        self.assertEqual(self.post(operation="read", vulgo="Newton", pin="01234").status_code, 409)
        self.event.signup_enabled = True
        self.event.save()
        self.signup.delete()
        self.assertEqual(self.post(operation="read", vulgo="Newton", pin="01234").status_code, 403)

    def admin_user(self):
        user = User.objects.create_user(username="pin-admin", password="test-password")
        role, _ = Role.objects.get_or_create(code="ADMIN", defaults={"name": "Admin"})
        user.profile.roles.add(role)
        self.client.force_login(user)
        return user

    def test_admin_can_edit_reset_and_delete_after_deadline(self):
        self.admin_user()
        self.event.signup_deadline_at = timezone.now() - timedelta(days=1)
        self.event.signup_enabled = False
        self.event.save()
        self.signup.pin_hash = ""
        self.signup.save()
        prefix = f"signup-{self.signup.pk}-"
        url = reverse("event-edit", kwargs={"pk": self.event.pk})
        payload = {"action": "manage-signups", prefix + "signup_id": self.signup.pk,
                   prefix + "vulgo": "Newton", prefix + "attending": "False",
                   prefix + "col_" + self.column.key: "Neu"}
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.signup.refresh_from_db()
        self.assertFalse(self.signup.attending)
        self.assertEqual(self.signup.pin_hash, "")
        payload[prefix + "new_pin"] = "000001"
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.signup.refresh_from_db()
        self.assertTrue(check_password("000001", self.signup.pin_hash))
        logs = list(SignupAuditLog.objects.filter(signup_id=self.signup.pk).values_list("changes", flat=True))
        self.assertNotIn("000001", json.dumps(logs))
        self.assertNotIn(self.signup.pin_hash, json.dumps(logs))
        self.assertEqual(self.client.post(url, {"action": "delete-signup", "delete_signup_id": self.signup.pk}).status_code, 302)
        self.assertFalse(EventSignup.objects.filter(pk=self.signup.pk).exists())

    def test_regular_member_cannot_reset_pin(self):
        user = User.objects.create_user(username="member", password="test-password")
        self.client.force_login(user)
        self.assertEqual(self.client.post(reverse("event-edit", kwargs={"pk": self.event.pk}),
                                         {"action": "manage-signups"}).status_code, 403)

    def test_public_detail_never_contains_pin_or_private_values(self):
        self.column.is_public = False
        self.column.save()
        response = self.client.get(reverse("api-v1-event-detail", kwargs={"slug": self.event.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.signup.pin_hash, response.content.decode())
        self.assertNotIn("pin_hash", response.content.decode())
        self.assertNotIn("Vegi", response.content.decode())

    def test_update_validates_dynamic_fields_without_changing_record(self):
        self.column.is_required = True
        self.column.save()
        response = self.post(operation="update", vulgo="Newton", pin="01234", attending=False, values={})
        self.assertEqual(response.status_code, 400)
        self.signup.refresh_from_db()
        self.assertTrue(self.signup.attending)
        self.assertEqual(self.signup.values[self.column.key], "Vegi")

    def test_admin_reset_unlocks_and_invalidates_previous_pin(self):
        self.admin_user()
        EventSignup.objects.filter(pk=self.signup.pk).update(
            pin_failed_attempts=5, pin_locked_until=timezone.now() + timedelta(minutes=15))
        prefix = f"signup-{self.signup.pk}-"
        payload = {"action": "manage-signups", prefix + "signup_id": self.signup.pk,
                   prefix + "vulgo": "Newton", prefix + "attending": "True", prefix + "new_pin": "0000"}
        self.assertEqual(self.client.post(reverse("event-edit", kwargs={"pk": self.event.pk}), payload).status_code, 302)
        self.assertEqual(self.post(operation="read", vulgo="Newton", pin="01234").status_code, 403)
        self.assertEqual(self.post(operation="read", vulgo="Newton", pin="0000").status_code, 200)
