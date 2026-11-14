import json
from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from .forms import EventForm
from .models import Event
from .public_views import _event_to_payload, _homepage_queryset, _public_queryset
from .signing import compute_signature


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class EventInternalFlagTests(TestCase):
    def setUp(self):
        cache.clear()
        self.start = timezone.now() + timedelta(days=10)
        self.event = Event.objects.create(
            title="Combined status", status="OFF", start=self.start,
            end=self.start + timedelta(hours=2), location="Basel",
            short_description="Description", is_public=True,
        )
        self.manager = User.objects.create_user("event-manager")
        self.manager.profile.roles.add(Role.objects.get(code="WEB_X"))

    def payload(self, **overrides):
        data = {
            "title": "Edited event", "status": "OFF", "is_internal": "on",
            "start": timezone.localtime(self.start).strftime("%Y-%m-%dT%H:%M"),
            "end": timezone.localtime(self.start + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
            "location": "Basel", "short_description": "Description", "is_public": "on",
            "columns-TOTAL_FORMS": "0", "columns-INITIAL_FORMS": "0",
            "columns-MIN_NUM_FORMS": "0", "columns-MAX_NUM_FORMS": "1000",
        }
        data.update(overrides)
        return data

    def test_all_four_statuses_allow_internal_and_external(self):
        for status in ("OFF", "INOFF", "IAOFF", "HOCHOFF"):
            for internal in (False, True):
                with self.subTest(status=status, internal=internal):
                    form = EventForm(self.payload(status=status, is_internal=internal), instance=self.event)
                    self.assertTrue(form.is_valid(), form.errors)
                    event = form.save()
                    event.refresh_from_db()
                    self.assertEqual(event.status, status)
                    self.assertEqual(event.is_internal, internal)
                    self.assertEqual(" + Intern" in event.status_label, internal)
                    self.assertTrue(event.is_public)

    def test_new_form_only_offers_four_primary_statuses(self):
        values = {value for value, label in EventForm().fields["status"].choices if value}
        self.assertEqual(values, {"OFF", "INOFF", "IAOFF", "HOCHOFF"})
        self.assertFalse(EventForm(self.payload(status="INTERN")).is_valid())

    def test_legacy_internal_preserved_and_can_gain_primary_status(self):
        self.event.status = "INTERN"
        self.event.save()
        self.event.refresh_from_db()
        self.assertTrue(self.event.is_internal)
        self.assertEqual(self.event.status_label, "Intern")
        form = EventForm(self.payload(status="INTERN"), instance=self.event)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        invalid = EventForm(self.payload(status="INTERN", is_internal=False), instance=self.event)
        self.assertFalse(invalid.is_valid())
        form = EventForm(self.payload(status="HOCHOFF"), instance=self.event)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().status_label, "Hochoff + Intern")

    def test_internal_cannot_be_on_homepage_but_can_remain_public(self):
        self.event.is_internal = True
        self.event.show_on_homepage = True
        with self.assertRaises(ValidationError):
            self.event.full_clean()
        # Defensive API exclusion even if a caller bypasses model validation.
        self.event.save()
        self.assertNotIn(self.event, _homepage_queryset())
        self.assertIn(self.event, _public_queryset())
        payload = _event_to_payload(self.event)
        self.assertEqual(payload["status"], "OFF")
        self.assertEqual(payload["status_label"], "Off + Intern")
        self.assertIs(payload["is_internal"], True)
        self.assertTrue(self.event.signup_enabled)

    def test_flag_change_updates_calendar_sequence(self):
        sequence = self.event.calendar_sequence
        self.event.is_internal = True
        self.event.save()
        self.event.refresh_from_db()
        self.assertEqual(self.event.calendar_sequence, sequence + 1)

    @override_settings(PUBLIC_EVENT_SIGNUP_SHARED_SECRET="internal-flag-test")
    def test_public_signup_is_not_restricted_by_this_preparatory_change(self):
        self.event.is_internal = True
        self.event.save()
        detail = self.client.get(reverse("api-v1-event-detail", args=[self.event.slug]))
        self.assertIs(detail.json()["is_internal"], True)
        self.assertTrue(detail.json()["signup_open"])
        body = json.dumps({"vulgo": "Test", "attending": True, "pin": "1234", "values": {}}).encode()
        timestamp = str(int(timezone.now().timestamp()))
        signature = compute_signature("internal-flag-test", self.event.slug, timestamp, body)
        response = self.client.post(
            reverse("api-v1-event-signup", args=[self.event.slug]), data=body,
            content_type="application/json", HTTP_X_AVF_TIMESTAMP=timestamp,
            HTTP_X_AVF_SIGNATURE=signature,
        )
        self.assertEqual(response.status_code, 201)

    def test_manager_create_edit_and_filter_combination(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse("event-create"), self.payload(status="INOFF"))
        self.assertEqual(response.status_code, 302)
        created = Event.objects.get(title="Edited event")
        self.assertEqual(created.status_label, "Inoff + Intern")
        response = self.client.get(reverse("event-list"), {"status": "INTERN"})
        self.assertContains(response, "Inoff + Intern")
        self.assertEqual(list(response.context["events"]), [created])
        response = self.client.post(reverse("event-edit", args=[created.pk]), self.payload(is_internal=False))
        self.assertEqual(response.status_code, 302)
        created.refresh_from_db()
        self.assertFalse(created.is_internal)

    def test_regular_member_cannot_create_or_edit_flags(self):
        member = User.objects.create_user("event-reader")
        self.client.force_login(member)
        for url in (reverse("event-create"), reverse("event-edit", args=[self.event.pk])):
            self.assertEqual(self.client.post(url, self.payload()).status_code, 403)
        self.event.refresh_from_db()
        self.assertFalse(self.event.is_internal)

    def test_migration_marks_only_legacy_internal_records(self):
        # Emulate pre-migration rows, bypassing the compatibility save hook.
        Event.objects.filter(pk=self.event.pk).update(status="INTERN", is_internal=False)
        other = Event.objects.create(title="External", status="OFF", start=self.start, end=self.start)
        migration = import_module("events.migrations.0011_event_is_internal")
        migration.mark_legacy_internal_events(apps, SimpleNamespace(connection=connection))
        self.event.refresh_from_db()
        other.refresh_from_db()
        self.assertTrue(self.event.is_internal)
        self.assertEqual(self.event.status, "INTERN")
        self.assertFalse(other.is_internal)
