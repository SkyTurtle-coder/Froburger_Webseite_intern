import json
from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from accounts.models import CalendarSubscription, Role
from events import signing
from events.models import Event, EventSignup, EventSignupColumn, SignupAuditLog

TEST_SIGNUP_SECRET = "test-signing-secret-not-a-real-value"


class EventModelTests(TestCase):
    def test_end_must_not_be_before_start(self):
        start = timezone.make_aware(datetime(2026, 8, 1, 20, 0))
        end = timezone.make_aware(datetime(2026, 8, 1, 18, 0))
        event = Event(title="Fehlerhaft", start=start, end=end, status="INTERN")

        with self.assertRaises(ValidationError):
            event.full_clean()

    def test_wordpress_visible_event_requires_summary_and_location(self):
        start = timezone.make_aware(datetime(2026, 8, 1, 18, 0))
        end = timezone.make_aware(datetime(2026, 8, 1, 20, 0))
        event = Event(title="Oeffentlich", start=start, end=end, status="OFF", is_public=True)

        with self.assertRaises(ValidationError):
            event.full_clean()

    def test_internal_event_cannot_be_on_homepage(self):
        start = timezone.make_aware(datetime(2026, 8, 1, 18, 0))
        end = timezone.make_aware(datetime(2026, 8, 1, 20, 0))
        event = Event(
            title="Interner WordPress Anlass",
            short_description="Nur auf Veranstaltungsseite",
            start=start,
            end=end,
            location="Basel",
            status="INTERN",
            is_public=True,
            show_on_homepage=True,
        )

        with self.assertRaises(ValidationError):
            event.full_clean()

    def test_homepage_requires_wordpress_visibility(self):
        start = timezone.make_aware(datetime(2026, 8, 1, 18, 0))
        end = timezone.make_aware(datetime(2026, 8, 1, 20, 0))
        event = Event(
            title="Nur Startseite",
            start=start,
            end=end,
            location="Basel",
            status="OFF",
            show_on_homepage=True,
        )

        with self.assertRaises(ValidationError):
            event.full_clean()

    @override_settings(TIME_ZONE="Europe/Zurich")
    def test_signup_deadline_is_local_day_at_0001(self):
        event = Event(
            title="Fruehanlass",
            short_description="Kurz",
            description="Text",
            start=timezone.make_aware(datetime(2026, 8, 12, 20, 0)),
            end=timezone.make_aware(datetime(2026, 8, 12, 22, 0)),
            location="Basel",
            status="OFF",
            is_public=True,
        )

        deadline = event.signup_deadline

        self.assertEqual(timezone.localtime(deadline).strftime("%Y-%m-%d %H:%M"), "2026-08-12 00:01")

    def test_signup_normalizes_vulgo_whitespace_and_case(self):
        now = timezone.now() + timedelta(days=7)
        event = Event.objects.create(
            title="Anlass",
            short_description="Kurz",
            description="Text",
            start=now,
            end=now + timedelta(hours=2),
            location="Basel",
            status="OFF",
            is_public=True,
        )
        signup = EventSignup.objects.create(event=event, vulgo="  NewTon   Max ", attending=True, values={})

        self.assertEqual(signup.vulgo, "NewTon Max")
        self.assertEqual(signup.normalized_vulgo, "newton max")

    def test_signup_duplicate_vulgo_is_blocked_per_event(self):
        now = timezone.now() + timedelta(days=7)
        event = Event.objects.create(
            title="Anlass",
            short_description="Kurz",
            description="Text",
            start=now,
            end=now + timedelta(hours=2),
            location="Basel",
            status="OFF",
            is_public=True,
        )
        EventSignup.objects.create(event=event, vulgo="Newton", attending=True, values={})
        duplicate = EventSignup(event=event, vulgo=" newton ", attending=False, values={})

        with self.assertRaises(ValidationError):
            duplicate.save()

    def test_soft_deleted_signup_frees_vulgo_for_reuse(self):
        now = timezone.now() + timedelta(days=7)
        event = Event.objects.create(
            title="Anlass",
            short_description="Kurz",
            description="Text",
            start=now,
            end=now + timedelta(hours=2),
            location="Basel",
            status="OFF",
            is_public=True,
        )
        signup = EventSignup.objects.create(event=event, vulgo="Newton", attending=True, values={})

        signup.delete(reason="Test")

        replacement = EventSignup.objects.create(event=event, vulgo="Newton", attending=False, values={})
        self.assertIsNotNone(replacement.pk)
        self.assertEqual(EventSignup.objects.filter(event=event).count(), 1)
        self.assertEqual(EventSignup.all_objects.filter(event=event).count(), 2)

    def test_signup_audit_log_tracks_create_update_delete_restore(self):
        now = timezone.now() + timedelta(days=7)
        user = User.objects.create_user(username="audit-user", password="testpass123")
        event = Event.objects.create(
            title="Anlass",
            short_description="Kurz",
            description="Text",
            start=now,
            end=now + timedelta(hours=2),
            location="Basel",
            status="OFF",
            is_public=True,
        )
        signup = EventSignup(
            event=event,
            vulgo="Newton",
            attending=True,
            values={},
        )
        signup.save(source=EventSignup.SOURCE_PUBLIC_FORM)

        created_log = SignupAuditLog.objects.get(signup_id=signup.pk, action=SignupAuditLog.ACTION_CREATED)
        self.assertEqual(created_log.source, SignupAuditLog.SOURCE_PUBLIC_FORM)

        signup.vulgo = "Newton II"
        signup.save(actor=user, source=EventSignup.SOURCE_INTERNAL)
        updated_log = SignupAuditLog.objects.filter(signup_id=signup.pk, action=SignupAuditLog.ACTION_UPDATED).latest("created_at")
        self.assertEqual(updated_log.actor, user)
        self.assertEqual(updated_log.changes["vulgo"], ["Newton", "Newton II"])

        signup.delete(actor=user, reason="Versehentlich", source=EventSignup.SOURCE_INTERNAL)
        signup = EventSignup.all_objects.get(pk=signup.pk)
        deleted_log = SignupAuditLog.objects.filter(signup_id=signup.pk, action=SignupAuditLog.ACTION_DELETED).latest("created_at")
        self.assertEqual(deleted_log.changes["delete_reason"], ["", "Versehentlich"])

        signup.restore(actor=user, source=EventSignup.SOURCE_INTERNAL)
        restored_log = SignupAuditLog.objects.filter(signup_id=signup.pk, action=SignupAuditLog.ACTION_RESTORED).latest("created_at")
        self.assertEqual(restored_log.actor, user)


class EventPublicApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.upcoming = Event.objects.create(
            title="Oeffentlicher Anlass",
            short_description="Kurz und klar",
            description="Volltext",
            start=now + timedelta(days=2),
            end=now + timedelta(days=2, hours=3),
            location="Basel",
            status="OFF",
            is_public=True,
            show_on_homepage=True,
        )
        cls.past = Event.objects.create(
            title="Vergangener Anlass",
            short_description="Vergangen",
            description="Vergangen",
            start=now - timedelta(days=5),
            end=now - timedelta(days=5) + timedelta(hours=2),
            location="Zuerich",
            status="HOCHOFF",
            is_public=True,
            show_on_homepage=True,
        )
        cls.internal_wordpress = Event.objects.create(
            title="Interner Veranstaltungsseiten-Anlass",
            short_description="Nur auf der Veranstaltungsseite sichtbar",
            description="Intern, aber auf WordPress sichtbar",
            start=now + timedelta(days=1),
            end=now + timedelta(days=1, hours=2),
            location="Bern",
            status="INTERN",
            is_public=True,
            show_on_homepage=False,
        )
        Event.objects.create(
            title="Versteckter interner Anlass",
            short_description="Unsichtbar",
            description="Unsichtbar",
            start=now + timedelta(days=4),
            end=now + timedelta(days=4, hours=2),
            location="Luzern",
            status="INTERN",
            is_public=False,
        )
        cls.public_column = EventSignupColumn.objects.create(
            event=cls.internal_wordpress,
            label="Essen",
            field_type=EventSignupColumn.FIELD_TYPE_SELECT,
            sort_order=10,
            is_active=True,
            is_required=True,
            is_public=True,
            field_options="Alles\nVegetarisch\nVegan",
        )
        cls.private_column = EventSignupColumn.objects.create(
            event=cls.internal_wordpress,
            label="Allergien",
            field_type=EventSignupColumn.FIELD_TYPE_TEXTAREA,
            sort_order=20,
            is_active=True,
            is_required=False,
            is_public=False,
            placeholder="Optional",
        )
        EventSignup.objects.create(
            event=cls.internal_wordpress,
            vulgo="Newton",
            attending=True,
            values={
                cls.public_column.key: "Vegetarisch",
                cls.private_column.key: "Haselnuss",
            },
        )
        EventSignup.objects.create(
            event=cls.internal_wordpress,
            vulgo="Nicht Oeffentlich",
            attending=False,
            is_public=False,
            values={
                cls.public_column.key: "Alles",
                cls.private_column.key: "Intern",
            },
        )

    def test_legacy_upcoming_api_returns_expected_shape(self):
        response = self.client.get(reverse("api-public-events-upcoming"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("count", payload)
        self.assertIn("results", payload)
        self.assertNotIn("next", payload)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["slug"], self.upcoming.slug)

    def test_legacy_upcoming_api_hides_internal_wordpress_events(self):
        response = self.client.get(reverse("api-public-events-upcoming"))
        payload = response.json()
        slugs = [item["slug"] for item in payload["results"]]
        self.assertNotIn(self.internal_wordpress.slug, slugs)

    def test_v1_upcoming_api_returns_wordpress_events_including_internal(self):
        response = self.client.get(reverse("api-v1-events-upcoming"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 2)

        event = next(item for item in payload["results"] if item["slug"] == self.upcoming.slug)
        self.assertEqual(event["status"], "OFF")
        self.assertEqual(event["status_label"], "Off")
        self.assertIn("next", payload)
        self.assertIn("previous", payload)
        slugs = [item["slug"] for item in payload["results"]]
        self.assertIn(self.upcoming.slug, slugs)
        self.assertIn(self.internal_wordpress.slug, slugs)

    def test_v1_past_api_only_returns_past_wordpress_events(self):
        response = self.client.get(reverse("api-v1-events-past"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["slug"], self.past.slug)
        self.assertNotEqual(payload["results"][0]["slug"], self.upcoming.slug)

    def test_v1_detail_api_returns_single_object_for_wordpress_internal_event(self):
        response = self.client.get(reverse("api-v1-event-detail", kwargs={"slug": self.internal_wordpress.slug}))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["slug"], self.internal_wordpress.slug)
        self.assertEqual(payload["short_description"], self.internal_wordpress.short_description)
        self.assertEqual(payload["location"], self.internal_wordpress.location)
        self.assertTrue(payload["signup_enabled"])
        self.assertTrue(payload["signup_open"])
        self.assertEqual(len(payload["signup_columns"]), 2)
        self.assertEqual(payload["signup_columns"][0]["key"], self.public_column.key)
        self.assertTrue(payload["signup_columns"][0]["public"])
        self.assertFalse(payload["signup_columns"][1]["public"])
        self.assertEqual(payload["signups"][0]["values"], {self.public_column.key: "Vegetarisch"})
        self.assertEqual(len(payload["signups"]), 1)
        self.assertIn("created_at", payload["signups"][0])

    def test_v1_detail_api_hides_non_wordpress_event(self):
        response = self.client.get(reverse("api-v1-event-detail", kwargs={"slug": "versteckter-interner-anlass"}))
        self.assertEqual(response.status_code, 404)

    def test_v1_list_limit_and_offset_are_supported(self):
        Event.objects.create(
            title="Zweiter oeffentlicher Anlass",
            short_description="Noch einer",
            description="Noch einer",
            start=timezone.now() + timedelta(days=3),
            end=timezone.now() + timedelta(days=3, hours=2),
            location="Luzern",
            status="OFF",
            is_public=True,
        )

        response = self.client.get(reverse("api-v1-events-upcoming"), {"limit": 1, "offset": 1})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["results"]), 1)
        self.assertIsNotNone(payload["previous"])

    def test_calendar_feed_returns_ics(self):
        response = self.client.get(reverse("api-v1-events-calendar"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/calendar", response["Content-Type"])
        content = response.content.decode("utf-8")
        self.assertIn("BEGIN:VCALENDAR", content)
        self.assertIn("BEGIN:VEVENT", content)
        self.assertIn(self.upcoming.title, content)
        self.assertIn(self.internal_wordpress.title, content)
        self.assertIn(self.upcoming.calendar_uid, content)
        self.assertIn("Europe/Zurich", content)

    def test_public_calendar_feed_has_stable_etag_and_supports_304(self):
        first = self.client.get(reverse("public-calendar-feed"))
        self.assertEqual(first.status_code, 200)
        self.assertIn("ETag", first)
        etag = first["ETag"]

        second = self.client.get(reverse("public-calendar-feed"), HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(second.status_code, 304)

    def test_single_event_calendar_uses_same_uid_as_feed(self):
        feed = self.client.get(reverse("public-calendar-feed")).content.decode("utf-8")
        single = self.client.get(reverse("public-event-calendar", kwargs={"slug": self.upcoming.slug}))
        self.assertEqual(single.status_code, 200)
        single_content = single.content.decode("utf-8")
        self.assertIn(self.upcoming.calendar_uid, feed)
        self.assertIn(self.upcoming.calendar_uid, single_content)
        self.assertIn(f"SUMMARY:{self.upcoming.title}", single_content)

    def test_public_calendar_feed_updates_etag_after_event_change(self):
        first = self.client.get(reverse("public-calendar-feed"))
        self.upcoming.title = "Geaenderter Anlass"
        self.upcoming.save()
        second = self.client.get(reverse("public-calendar-feed"))
        self.assertNotEqual(first["ETag"], second["ETag"])
        self.assertIn("SEQUENCE:1", second.content.decode("utf-8"))

    def test_cancelled_public_events_are_excluded_from_lists_but_remain_in_calendar(self):
        self.internal_wordpress.is_cancelled = True
        self.internal_wordpress.save()

        list_response = self.client.get(reverse("api-v1-events-upcoming"))
        list_slugs = [item["slug"] for item in list_response.json()["results"]]
        self.assertNotIn(self.internal_wordpress.slug, list_slugs)

        calendar_response = self.client.get(reverse("public-calendar-feed"))
        self.assertIn("STATUS:CANCELLED", calendar_response.content.decode("utf-8"))

    def test_deleted_public_events_leave_cancelled_tombstone(self):
        uid = self.upcoming.calendar_uid
        self.upcoming.delete()

        calendar_response = self.client.get(reverse("public-calendar-feed"))
        content = calendar_response.content.decode("utf-8")
        self.assertIn(uid, content)
        self.assertIn("STATUS:CANCELLED", content)

    @override_settings(PUBLIC_EVENT_SOURCE_BASE_URL="https://intern.avfroburger.test")
    def test_source_url_is_emitted_when_configured(self):
        response = self.client.get(reverse("api-v1-event-detail", kwargs={"slug": self.upcoming.slug}))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source_url"], f"https://intern.avfroburger.test/anlaesse/{self.upcoming.slug}/")

    def test_public_event_detail_route_is_removed(self):
        with self.assertRaises(NoReverseMatch):
            reverse("public-event-detail", kwargs={"slug": self.internal_wordpress.slug})


@override_settings(PUBLIC_EVENT_SIGNUP_SHARED_SECRET=TEST_SIGNUP_SECRET)
class EventPublicSignupApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now() + timedelta(days=3)
        cls.event = Event.objects.create(
            title="API Signup Anlass",
            short_description="Kurz",
            description="Volltext",
            start=now,
            end=now + timedelta(hours=2),
            location="Basel",
            status="OFF",
            is_public=True,
            signup_enabled=True,
        )
        cls.public_column = EventSignupColumn.objects.create(
            event=cls.event,
            label="Essen",
            field_type=EventSignupColumn.FIELD_TYPE_SELECT,
            sort_order=10,
            is_active=True,
            is_required=True,
            is_public=True,
            field_options="Alles\nVegetarisch\nVegan",
        )
        cls.private_column = EventSignupColumn.objects.create(
            event=cls.event,
            label="Allergien",
            field_type=EventSignupColumn.FIELD_TYPE_TEXT,
            sort_order=20,
            is_active=True,
            is_required=False,
            is_public=False,
        )

    def setUp(self):
        cache.clear()

    def _post(self, payload):
        body = json.dumps(payload).encode("utf-8")
        timestamp = str(int(timezone.now().timestamp()))
        signature = signing.compute_signature(TEST_SIGNUP_SECRET, self.event.slug, timestamp, body)
        return self.client.post(
            reverse("api-v1-event-signup", kwargs={"slug": self.event.slug}),
            data=body,
            content_type="application/json",
            HTTP_X_AVF_TIMESTAMP=timestamp,
            HTTP_X_AVF_SIGNATURE=signature,
        )

    def test_signup_api_creates_signup(self):
        response = self._post(
            {
                "vulgo": "Newton",
                "attending": True,
                "values": {
                    self.public_column.key: "Vegetarisch",
                    self.private_column.key: "Haselnuss",
                },
            }
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload["success"])
        signup = EventSignup.objects.get(event=self.event, normalized_vulgo="newton")
        self.assertEqual(signup.values[self.public_column.key], "Vegetarisch")
        self.assertEqual(signup.values[self.private_column.key], "Haselnuss")

    def test_signup_api_rejects_duplicate_vulgo(self):
        EventSignup.objects.create(
            event=self.event,
            vulgo="Newton",
            attending=True,
            values={self.public_column.key: "Alles"},
        )

        response = self._post(
            {
                "vulgo": " newton ",
                "attending": False,
                "values": {self.public_column.key: "Vegetarisch"},
            }
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "duplicate_signup")

    def test_signup_api_rejects_unknown_fields(self):
        response = self._post(
            {
                "vulgo": "Euler",
                "attending": True,
                "values": {"unbekannt": "x"},
            }
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "unknown_fields")

    def test_signup_api_rejects_when_deadline_has_passed(self):
        self.event.start = timezone.now() - timedelta(hours=2)
        self.event.end = timezone.now() + timedelta(hours=1)
        self.event.save(update_fields=["start", "end"])

        response = self._post(
            {
                "vulgo": "Gauss",
                "attending": True,
                "values": {self.public_column.key: "Alles"},
            }
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "signup_closed")

    @override_settings(PUBLIC_EVENT_SIGNUP_SHARED_SECRET="supersecret")
    def test_signup_api_rejects_invalid_server_secret(self):
        response = self.client.post(
            reverse("api-v1-event-signup", kwargs={"slug": self.event.slug}),
            data=json.dumps(
                {
                    "vulgo": "Bernoulli",
                    "attending": True,
                    "values": {self.public_column.key: "Alles"},
                }
            ),
            content_type="application/json",
            HTTP_X_AVF_EVENT_SECRET="wrong",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "invalid_authentication")

    def test_signup_api_rate_limits_repeat_submit(self):
        first = self._post(
            {
                "vulgo": "Leibniz",
                "attending": True,
                "values": {self.public_column.key: "Alles"},
            }
        )
        second = self._post(
            {
                "vulgo": "Laplace",
                "attending": True,
                "values": {self.public_column.key: "Alles"},
            }
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["code"], "rate_limited")


class EventSignupApiAuthenticationTests(TestCase):
    """SEC-005: the signup endpoint must fail closed, verify HMAC-signed
    requests correctly, and reject stale/replayed/tampered ones."""

    @classmethod
    def setUpTestData(cls):
        now = timezone.now() + timedelta(days=3)
        cls.event = Event.objects.create(
            title="Signierter Anlass",
            short_description="Kurz",
            description="Volltext",
            start=now,
            end=now + timedelta(hours=2),
            location="Basel",
            status="OFF",
            is_public=True,
            signup_enabled=True,
        )

    def setUp(self):
        cache.clear()

    def _body(self, vulgo="Riemann"):
        return json.dumps({"vulgo": vulgo, "attending": True, "values": {}}).encode("utf-8")

    def _post(self, body, headers=None):
        return self.client.post(
            reverse("api-v1-event-signup", kwargs={"slug": self.event.slug}),
            data=body,
            content_type="application/json",
            **(headers or {}),
        )

    def _signed_headers(self, slug, body, secret=TEST_SIGNUP_SECRET, timestamp=None):
        ts = str(int(timestamp if timestamp is not None else timezone.now().timestamp()))
        signature = signing.compute_signature(secret, slug, ts, body)
        return {
            "HTTP_X_AVF_TIMESTAMP": ts,
            "HTTP_X_AVF_SIGNATURE": signature,
        }

    def test_signup_rejected_when_secret_not_configured(self):
        # No override_settings here: PUBLIC_EVENT_SIGNUP_SHARED_SECRET is "" by
        # default in the test environment - this must never be treated as "no
        # auth required" (the SEC-005 bug being fixed).
        body = self._body()
        response = self._post(body, self._signed_headers(self.event.slug, body, secret="anything"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "signup_unavailable")
        self.assertFalse(EventSignup.objects.filter(event=self.event).exists())

    @override_settings(PUBLIC_EVENT_SIGNUP_SHARED_SECRET=TEST_SIGNUP_SECRET)
    def test_signup_accepts_valid_signature(self):
        body = self._body("Riemann")
        response = self._post(body, self._signed_headers(self.event.slug, body))
        self.assertEqual(response.status_code, 201)
        self.assertTrue(EventSignup.objects.filter(event=self.event, normalized_vulgo="riemann").exists())

    @override_settings(PUBLIC_EVENT_SIGNUP_SHARED_SECRET=TEST_SIGNUP_SECRET)
    def test_signup_rejects_invalid_signature(self):
        body = self._body("Cauchy")
        headers = self._signed_headers(self.event.slug, body)
        headers["HTTP_X_AVF_SIGNATURE"] = "0" * 64
        response = self._post(body, headers)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "invalid_authentication")
        self.assertFalse(EventSignup.objects.filter(event=self.event).exists())

    @override_settings(PUBLIC_EVENT_SIGNUP_SHARED_SECRET=TEST_SIGNUP_SECRET)
    def test_signup_rejects_stale_timestamp(self):
        body = self._body("Fourier")
        stale = timezone.now().timestamp() - (signing.DEFAULT_TOLERANCE_SECONDS + 60)
        response = self._post(body, self._signed_headers(self.event.slug, body, timestamp=stale))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "invalid_authentication")

    @override_settings(PUBLIC_EVENT_SIGNUP_SHARED_SECRET=TEST_SIGNUP_SECRET)
    def test_signup_rejects_body_tampered_after_signing(self):
        signed_body = self._body("Laplace")
        headers = self._signed_headers(self.event.slug, signed_body)
        tampered_body = self._body("Laplace-Angreifer")
        response = self._post(tampered_body, headers)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(EventSignup.objects.filter(event=self.event).exists())

    @override_settings(PUBLIC_EVENT_SIGNUP_SHARED_SECRET=TEST_SIGNUP_SECRET)
    def test_signup_rejects_signature_issued_for_a_different_event(self):
        other_event = Event.objects.create(
            title="Anderer Anlass",
            short_description="Kurz",
            description="Text",
            start=self.event.start,
            end=self.event.end,
            location="Bern",
            status="OFF",
            is_public=True,
            signup_enabled=True,
        )
        body = self._body("Hilbert")
        # Signed for other_event.slug, but replayed against self.event's URL.
        headers = self._signed_headers(other_event.slug, body)
        response = self._post(body, headers)
        self.assertEqual(response.status_code, 403)

    @override_settings(PUBLIC_EVENT_SIGNUP_SHARED_SECRET=TEST_SIGNUP_SECRET)
    def test_signup_rejects_replayed_signature(self):
        body = self._body("Poincare")
        headers = self._signed_headers(self.event.slug, body)
        first = self._post(body, headers)
        self.assertEqual(first.status_code, 201)

        replay_body = self._body("Poincare-Replay")
        replay = self._post(replay_body, headers)
        self.assertEqual(replay.status_code, 403)
        self.assertFalse(EventSignup.objects.filter(normalized_vulgo="poincare-replay").exists())

    @override_settings(PUBLIC_EVENT_SIGNUP_SHARED_SECRET=TEST_SIGNUP_SECRET)
    def test_signup_rejects_legacy_secret_header(self):
        body = self._body("Legacy")
        response = self._post(body, {"HTTP_X_AVF_EVENT_SECRET": TEST_SIGNUP_SECRET})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "invalid_authentication")

    @override_settings(PUBLIC_EVENT_SIGNUP_SHARED_SECRET=TEST_SIGNUP_SECRET)
    def test_signup_rejects_wrong_legacy_secret(self):
        body = self._body("Legacy-Wrong")
        response = self._post(body, {"HTTP_X_AVF_EVENT_SECRET": "wrong-secret"})
        self.assertEqual(response.status_code, 403)


class PrivateCalendarFeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.role = Role.objects.get(code="BURSCH")
        cls.user = User.objects.create_user(username="mitglied", password="testpass123", is_active=True)
        cls.user.profile.roles.add(cls.role)
        now = timezone.now()
        cls.public_event = Event.objects.create(
            title="Oeffentlicher Kalenderanlass",
            short_description="Kurz",
            description="Text",
            start=now + timedelta(days=5),
            end=now + timedelta(days=5, hours=2),
            location="Basel",
            status="OFF",
            is_public=True,
        )
        cls.internal_event = Event.objects.create(
            title="Interner Kalenderanlass",
            short_description="Intern",
            description="Interner Text",
            start=now + timedelta(days=6),
            end=now + timedelta(days=6, hours=2),
            location="Bern",
            status="INTERN",
            is_public=False,
        )

    def test_private_feed_requires_valid_token(self):
        response = self.client.get(reverse("private-calendar-feed", kwargs={"token": "ungueltig"}))
        self.assertEqual(response.status_code, 404)

    def test_private_feed_contains_internal_and_public_events(self):
        _subscription, token = CalendarSubscription.issue_for_user(self.user)
        response = self.client.get(reverse("private-calendar-feed", kwargs={"token": token}))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn(self.public_event.title, content)
        self.assertIn(self.internal_event.title, content)
        self.assertIn("CLASS:PRIVATE", content)

    def test_revoked_subscription_returns_404(self):
        subscription, token = CalendarSubscription.issue_for_user(self.user)
        subscription.revoke()
        response = self.client.get(reverse("private-calendar-feed", kwargs={"token": token}))
        self.assertEqual(response.status_code, 404)


class EventSignupManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.webx_role = Role.objects.get(code="WEB_X")
        cls.bursch_role = Role.objects.get(code="BURSCH")
        cls.webx = User.objects.create_user(username="webx", password="testpass123")
        cls.webx.profile.roles.add(cls.webx_role)
        cls.member = User.objects.create_user(username="member", password="testpass123")
        cls.member.profile.roles.add(cls.bursch_role)

        now = timezone.now() + timedelta(days=4)
        cls.event = Event.objects.create(
            title="Editierbarer Anlass",
            short_description="Kurz",
            description="Text",
            start=now,
            end=now + timedelta(hours=3),
            location="Basel",
            status="OFF",
            is_public=True,
        )
        cls.column = EventSignupColumn.objects.create(event=cls.event, label="Essen", sort_order=20)
        cls.signup = EventSignup.objects.create(
            event=cls.event,
            vulgo="Newton",
            attending=True,
            values={cls.column.key: "Vegi"},
        )

    def test_non_webx_cannot_access_event_edit(self):
        self.client.login(username="member", password="testpass123")

        response = self.client.get(reverse("event-edit", kwargs={"pk": self.event.pk}))

        self.assertEqual(response.status_code, 403)

    def test_webx_can_update_signup_rows(self):
        self.client.login(username="webx", password="testpass123")

        response = self.client.post(
            reverse("event-edit", kwargs={"pk": self.event.pk}),
            {
                "action": "manage-signups",
                f"signup-{self.signup.pk}-signup_id": str(self.signup.pk),
                f"signup-{self.signup.pk}-vulgo": "Newton II",
                f"signup-{self.signup.pk}-attending": "False",
                f"signup-{self.signup.pk}-col_{self.column.key}": "Kein Essen",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.signup.refresh_from_db()
        self.assertEqual(self.signup.vulgo, "Newton II")
        self.assertFalse(self.signup.attending)
        self.assertEqual(self.signup.values[self.column.key], "Kein Essen")

    def test_webx_can_soft_delete_signup_row(self):
        self.client.login(username="webx", password="testpass123")

        response = self.client.post(
            reverse("event-edit", kwargs={"pk": self.event.pk}),
            {
                "action": "delete-signup",
                "delete_signup_id": str(self.signup.pk),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(EventSignup.objects.filter(pk=self.signup.pk).exists())
        deleted_signup = EventSignup.all_objects.get(pk=self.signup.pk)
        self.assertIsNotNone(deleted_signup.deleted_at)

    def test_webx_can_manage_columns_on_event_form(self):
        self.client.login(username="webx", password="testpass123")

        response = self.client.post(
            reverse("event-edit", kwargs={"pk": self.event.pk}),
            {
                "title": self.event.title,
                "slug": self.event.slug,
                "short_description": self.event.short_description,
                "description": self.event.description,
                "start": timezone.localtime(self.event.start).strftime("%Y-%m-%dT%H:%M"),
                "end": timezone.localtime(self.event.end).strftime("%Y-%m-%dT%H:%M"),
                "location": self.event.location,
                "status": self.event.status,
                "is_public": "on",
                "columns-TOTAL_FORMS": "2",
                "columns-INITIAL_FORMS": "1",
                "columns-MIN_NUM_FORMS": "0",
                "columns-MAX_NUM_FORMS": "1000",
                "columns-0-id": str(self.column.pk),
                "columns-0-label": "Menu",
                "columns-0-field_type": "text",
                "columns-0-sort_order": "20",
                "columns-0-is_active": "on",
                "columns-0-is_required": "",
                "columns-0-is_public": "",
                "columns-0-field_options": "",
                "columns-0-placeholder": "",
                "columns-1-id": "",
                "columns-1-label": "Notiz",
                "columns-1-field_type": "textarea",
                "columns-1-sort_order": "30",
                "columns-1-is_active": "on",
                "columns-1-is_required": "",
                "columns-1-is_public": "",
                "columns-1-field_options": "",
                "columns-1-placeholder": "Optional",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(EventSignupColumn.objects.filter(event=self.event, label="Menu").exists())
        self.assertTrue(EventSignupColumn.objects.filter(event=self.event, label="Notiz").exists())

    def test_event_create_form_hides_api_hint_and_uses_add_button_for_columns(self):
        self.client.login(username="webx", password="testpass123")

        response = self.client.get(reverse("event-create"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertNotIn("API-Hinweis", content)
        self.assertIn('id="add-signup-column"', content)
        self.assertIn("Noch keine Zusatzspalten angelegt.", content)
