import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from .member_signup import ATTEMPT_LIMIT, BLOCK_SECONDS, DENIED_MESSAGE, attempt_allowed, record_failure
from .models import Event, EventSignup, SignupAttemptWindow
from .signing import compute_signature
from .views import PublicEventDetailView


@override_settings(PUBLIC_EVENT_SIGNUP_SHARED_SECRET="member-test",
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class MemberSignupTests(TestCase):
    def setUp(self):
        cache.clear()
        start = timezone.now() + timedelta(days=10)
        self.event = Event.objects.create(title="Private", status="OFF", is_internal=True,
                                         is_public=True, start=start, end=start + timedelta(hours=2))
        self.member = User.objects.create_user("member").profile
        self.member.vulgo = "Alpha Beta"
        self.member.save()
        self.member.roles.add(Role.objects.get(code="BURSCH"))
        self.counter = 0

    def send(self, **changes):
        self.counter += 1
        payload = {"vulgo": "Alpha Beta", "pin": "1234", "attending": True, "values": {},
                   "client_key": "a" * 64}
        payload.update(changes)
        if payload.get("operation") == "read":
            payload.pop("attending")
            payload.pop("values")
        body = json.dumps(payload).encode()
        timestamp = str(int(timezone.now().timestamp()) + self.counter)
        return self.client.post(reverse("api-v1-event-signup", args=[self.event.slug]), data=body,
                                content_type="application/json", HTTP_X_AVF_TIMESTAMP=timestamp,
                                HTTP_X_AVF_SIGNATURE=compute_signature("member-test", self.event.slug, timestamp, body))

    def assert_denied(self, response):
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"success": False, "code": "member_signup_denied", "message": DENIED_MESSAGE})

    def test_active_and_alt_members_and_normalization(self):
        for role in ("FUX", "BURSCH", "SENIOR", "CONSENIOR", "FUXMAJOR", "AKTUAR", "QUAESTOR", "ALTFROBURGER"):
            with self.subTest(role=role):
                self.member.roles.set([Role.objects.get(code=role)])
                response = self.send(vulgo="  ALPHA   beta ")
                self.assertEqual(response.status_code, 201, response.content)
                signup = EventSignup.objects.get(event=self.event)
                self.assertEqual(signup.member_profile_id, self.member.pk)
                signup.delete()

    def test_unknown_duplicate_and_ineligible_have_same_response(self):
        self.assert_denied(self.send(vulgo="Unknown"))
        self.assertEqual(self.send().status_code, 201)
        self.assert_denied(self.send())
        self.member.roles.set([Role.objects.get(code="EHRENPHILISTER")])
        self.assert_denied(self.send())

    def test_excluded_roles(self):
        for role in ("ADMIN", "WEB_X", "EHRENPHILISTER", "AF_PRAESIDENT"):
            self.member.roles.set([Role.objects.get(code=role)])
            self.assert_denied(self.send())

    def test_disabled_exited_and_deceased(self):
        self.member.user.is_active = False
        self.member.user.save()
        self.assert_denied(self.send())
        self.member.user.is_active = True
        self.member.user.save()
        for field, value in (("death_date", timezone.now().date()), ("exit_year", 2025), ("exit_semester", "HS")):
            setattr(self.member, field, value)
            self.member.save()
            self.assert_denied(self.send())
            setattr(self.member, field, "" if field == "exit_semester" else None)
        self.member.save()

    def test_ambiguous_vulgo_denied(self):
        other = User.objects.create_user("other").profile
        other.vulgo = "alpha  beta"
        other.save()
        self.assert_denied(self.send())

    def test_rename_does_not_allow_duplicate_and_pin_still_works(self):
        self.assertEqual(self.send().status_code, 201)
        self.member.vulgo = "Gamma"
        self.member.save()
        self.assert_denied(self.send(vulgo="Gamma"))
        self.assert_denied(self.send(vulgo="Gamma", operation="read", pin="9999"))
        self.assertEqual(self.send(vulgo="Gamma", operation="read").status_code, 200)
        self.assertEqual(self.send(vulgo="Gamma", operation="update", attending=False).status_code, 200)
        self.assertFalse(EventSignup.objects.get().attending)

    def test_legacy_binding_requires_existing_pin(self):
        signup = EventSignup(event=self.event, vulgo="Alpha Beta", attending=True)
        signup.set_pin("5678")
        signup.save()
        self.assert_denied(self.send(operation="read"))
        signup.refresh_from_db()
        self.assertIsNone(signup.member_profile_id)
        self.assertEqual(self.send(operation="read", pin="5678").status_code, 200)
        signup.refresh_from_db()
        self.assertEqual(signup.member_profile_id, self.member.pk)

    def test_revoked_member_cannot_read_or_update(self):
        self.assertEqual(self.send().status_code, 201)
        self.member.roles.clear()
        for operation in ("read", "update"):
            self.assert_denied(self.send(operation=operation))

    def test_internal_payload_hides_participants_and_disables_cache(self):
        self.assertEqual(self.send().status_code, 201)
        response = self.client.get(reverse("api-v1-event-detail", args=[self.event.slug]))
        self.assertEqual(response.json()["signups"], [])
        self.assertNotIn(b"Alpha Beta", response.content)
        self.assertIn("no-store", response["Cache-Control"])

    def test_direct_public_form_cannot_bypass_policy(self):
        request = RequestFactory().post("/", {"vulgo": "Unknown", "pin": "1234", "attending": "True"})
        response = PublicEventDetailView.as_view()(request, slug=self.event.slug)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(EventSignup.objects.exists())

    def test_normal_events_remain_open_to_external_vulgos(self):
        self.event.is_internal = False
        self.event.save()
        self.assertEqual(self.send(vulgo="External").status_code, 201)
        detail = self.client.get(reverse("api-v1-event-detail", args=[self.event.slug])).json()
        self.assertEqual(detail["signups"][0]["vulgo"], "External")

    def test_legacy_internal_status_is_restricted(self):
        Event.objects.filter(pk=self.event.pk).update(status="INTERN", is_internal=False)
        self.assert_denied(self.send(vulgo="Unknown"))

    def test_rate_limit_counts_failures_across_operations_and_cache_resets(self):
        for number in range(5):
            self.assert_denied(self.send(vulgo="Missing" + str(number)))
            cache.clear()
        self.assert_denied(self.send())
        self.assertEqual(SignupAttemptWindow.objects.get().attempts, 5)
        SignupAttemptWindow.objects.update(blocked_until=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.send().status_code, 201)

    def test_unsigned_request_denied(self):
        response = self.client.post(reverse("api-v1-event-signup", args=[self.event.slug]),
                                    data=json.dumps({"vulgo": "Alpha Beta"}), content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(EventSignup.objects.exists())

    def test_invalid_fields_do_not_provide_a_membership_lookup(self):
        for number, changes in enumerate(({"pin": "bad"}, {"attending": "bad"}, {"operation": "lookup"}, {"extra": "bad"})):
            self.assert_denied(self.send(client_key=f"{number:064x}", **changes))
            self.assert_denied(self.send(vulgo="Unknown", client_key=f"{number:064x}", **changes))

    def test_member_cannot_claim_another_profiles_linked_signup(self):
        other = User.objects.create_user("other").profile
        signup = EventSignup(event=self.event, vulgo="Alpha Beta", attending=True, member_profile=other)
        signup.set_pin("1234")
        signup.save()
        self.assert_denied(self.send(operation="read"))

    def test_pin_lock_has_same_public_error(self):
        self.assertEqual(self.send().status_code, 201)
        for _ in range(5):
            self.assert_denied(self.send(operation="read", pin="9999"))
        self.assert_denied(self.send(operation="read"))

    def test_fifth_failure_blocks_valid_vulgos_without_querying_members(self):
        for _ in range(4):
            self.assert_denied(self.send(vulgo="Unknown"))
        self.assertIsNone(SignupAttemptWindow.objects.get().blocked_until)
        before = timezone.now()
        self.assert_denied(self.send(vulgo="Unknown"))
        window = SignupAttemptWindow.objects.get()
        self.assertGreaterEqual(window.blocked_until, before + timedelta(seconds=30))
        self.assertEqual(window.penalty_level, 1)
        with patch("events.public_views.resolve_member") as resolve:
            self.assert_denied(self.send())
            self.assert_denied(self.send(operation="read"))
            resolve.assert_not_called()
        window.refresh_from_db()
        self.assertEqual(window.failed_attempts, 0)
        self.assertEqual(window.attempts, 5)
        self.assertEqual(self.send(client_key="b" * 64).status_code, 201)

    def test_progressive_durations_expiry_and_maximum(self):
        now = timezone.now()
        with patch("events.member_signup.timezone") as clock:
            for duration in (*BLOCK_SECONDS, BLOCK_SECONDS[-1]):
                clock.now.return_value = now
                for _ in range(5):
                    self.assertTrue(attempt_allowed("visitor"))
                    record_failure("visitor")
                window = SignupAttemptWindow.objects.get()
                self.assertEqual(window.blocked_until, now + timedelta(seconds=duration))
                self.assertFalse(attempt_allowed("visitor"))
                # Retrying during a block must not move its deadline or tier.
                record_failure("visitor")
                window.refresh_from_db()
                self.assertEqual(window.blocked_until, now + timedelta(seconds=duration))
                now = window.blocked_until

    def test_escalation_resets_only_after_quiet_period(self):
        now = timezone.now()
        with patch("events.member_signup.timezone") as clock:
            clock.now.return_value = now
            for _ in range(5):
                self.assertTrue(attempt_allowed("visitor"))
                record_failure("visitor")
            clock.now.return_value = now + timedelta(seconds=30)
            self.assertTrue(attempt_allowed("visitor"))
            self.assertEqual(SignupAttemptWindow.objects.get().penalty_level, 1)
            clock.now.return_value = now + timedelta(seconds=30, days=1)
            self.assertTrue(attempt_allowed("visitor"))
            self.assertEqual(SignupAttemptWindow.objects.get().penalty_level, 0)
            for _ in range(5):
                record_failure("visitor")
            self.assertEqual(SignupAttemptWindow.objects.get().blocked_until, clock.now.return_value + timedelta(seconds=30))

    def test_success_does_not_erase_failed_attempts(self):
        for _ in range(4):
            self.assert_denied(self.send(vulgo="Unknown"))
        self.assertEqual(self.send().status_code, 201)
        self.assertEqual(SignupAttemptWindow.objects.get().failed_attempts, 4)
        self.assert_denied(self.send(vulgo="Unknown"))
        self.assertIsNotNone(SignupAttemptWindow.objects.get().blocked_until)

    def test_lock_applies_across_events(self):
        for _ in range(5):
            self.assert_denied(self.send(vulgo="Unknown"))
        start = timezone.now() + timedelta(days=10)
        self.event = Event.objects.create(title="Other", status="OFF", is_internal=True,
                                         is_public=True, start=start, end=start)
        self.assert_denied(self.send())

    def test_cleanup_preserves_escalation_and_general_limit_remains(self):
        now = timezone.now()
        with patch("events.member_signup.timezone") as clock:
            clock.now.return_value = now
            for _ in range(5):
                self.assertTrue(attempt_allowed("visitor"))
                record_failure("visitor")
            SignupAttemptWindow.objects.update(expires_at=now - timedelta(days=2))
            self.assertTrue(attempt_allowed("other"))
            self.assertEqual(SignupAttemptWindow.objects.count(), 2)
            for _ in range(ATTEMPT_LIMIT - 1):
                self.assertTrue(attempt_allowed("other"))
            self.assertFalse(attempt_allowed("other"))
            clock.now.return_value = now + timedelta(days=3)
            self.assertTrue(attempt_allowed("new"))
            self.assertEqual(SignupAttemptWindow.objects.count(), 1)
