from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from events.forms import EventForm
from events.models import Event


class EventStartTimingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.start = (timezone.now() + timedelta(days=7)).replace(second=0, microsecond=0)
        self.event = Event.objects.create(
            title="Zeitangabe", short_description="Test", location="Basel", status="OFF",
            start=self.start, end=self.start + timedelta(hours=2), is_public=True, show_on_homepage=True,
        )
        self.manager = User.objects.create_user("timing-webx")
        self.manager.profile.roles.add(Role.objects.get(code="WEB_X"))
        self.client.force_login(self.manager)

    def payload(self, timing):
        return {
            "title": self.event.title, "short_description": "Test", "location": "Basel", "status": "OFF",
            "start": timezone.localtime(self.start).strftime("%Y-%m-%dT%H:%M"),
            "end": timezone.localtime(self.event.end).strftime("%Y-%m-%dT%H:%M"),
            "start_timing": timing, "is_public": "on", "show_on_homepage": "on",
            "columns-TOTAL_FORMS": "0", "columns-INITIAL_FORMS": "0",
        }

    def test_existing_event_has_no_assumed_suffix(self):
        self.assertEqual(self.event.start_timing, "")
        form = EventForm(instance=self.event)
        self.assertFalse(form.fields["start_timing"].required)

    def test_editor_persists_and_clears_suffix_without_moving_time(self):
        url = reverse("event-edit", args=[self.event.pk])
        for timing, label in (("ct", "c.t."), ("st", "s.t."), ("", "")):
            with self.subTest(timing=timing):
                response = self.client.post(url, self.payload(timing))
                self.assertEqual(response.status_code, 302)
                self.event.refresh_from_db()
                self.assertEqual(self.event.start_timing, timing)
                self.assertEqual(self.event.start, self.start)
                if label:
                    self.assertContains(self.client.get(reverse("event-list")), label)
                response = self.client.get(url)
                self.assertContains(response, 'name="start_timing"')

    def test_invalid_timing_is_rejected(self):
        form = EventForm(self.payload("invalid"), instance=self.event)
        self.assertFalse(form.is_valid())
        self.assertIn("start_timing", form.errors)

    def test_list_detail_and_homepage_api_preserve_time_and_suffix(self):
        for timing in ("", "ct", "st"):
            self.event.start_timing = timing
            self.event.save()
            cache.clear()
            for url in (
                "/api/public/events/upcoming/",
                "/api/v1/public/events/upcoming/",
                f"/api/v1/public/events/{self.event.slug}/",
            ):
                with self.subTest(timing=timing, url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    data = response.json()
                    event = data["results"][0] if "results" in data else data
                    self.assertEqual(event["start_timing"], timing)
                    self.assertEqual(event["start_at"], timezone.localtime(self.start).isoformat())
