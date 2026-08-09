from io import StringIO
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from events.models import Event


class VerifyWordPressEventContractCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.event = Event.objects.create(
            title="API Test Event",
            short_description="Kurzbeschreibung",
            description="Langbeschreibung",
            start=now + timedelta(days=1),
            end=now + timedelta(days=1, hours=2),
            location="Basel",
            status="OFF",
            is_public=True,
        )

    @override_settings(PUBLIC_EVENT_SOURCE_BASE_URL="https://intern.avfroburger.test")
    @patch("core.management.commands.verify_wordpress_event_contract.Command.fetch_text")
    def test_command_accepts_valid_contract(self, fetch_text_mock):
        responses = {
            "https://intern.avfroburger.test/api/public/events/upcoming/": (
                '{"count": 1, "results": [{"id": 1, "title": "API Test Event", "slug": "api-test-event", "short_description": "Kurzbeschreibung", "start_at": "2026-07-24T18:00:00+02:00", "end_at": "2026-07-24T20:00:00+02:00", "timezone_name": "Europe/Zurich", "location_name": "Basel", "detail_path": "/anlaesse/api-test-event/", "source_url": "https://intern.avfroburger.test/anlaesse/api-test-event/"}]}',
                "application/json",
            ),
            "https://intern.avfroburger.test/api/v1/public/events/upcoming/": (
                '{"count": 1, "next": null, "previous": null, "results": [{"id": 1, "title": "API Test Event", "slug": "api-test-event", "short_description": "Kurzbeschreibung", "start_at": "2026-07-24T18:00:00+02:00", "end_at": "2026-07-24T20:00:00+02:00", "timezone_name": "Europe/Zurich", "location_name": "Basel", "detail_path": "/anlaesse/api-test-event/", "source_url": "https://intern.avfroburger.test/anlaesse/api-test-event/"}]}',
                "application/json",
            ),
            "https://intern.avfroburger.test/api/v1/public/events/past/": (
                '{"count": 0, "next": null, "previous": null, "results": []}',
                "application/json",
            ),
            "https://intern.avfroburger.test/api/v1/public/events/api-test-event/": (
                '{"id": 1, "title": "API Test Event", "slug": "api-test-event", "short_description": "Kurzbeschreibung", "start_at": "2026-07-24T18:00:00+02:00", "end_at": "2026-07-24T20:00:00+02:00", "timezone_name": "Europe/Zurich", "location_name": "Basel", "detail_path": "/anlaesse/api-test-event/", "source_url": "https://intern.avfroburger.test/anlaesse/api-test-event/"}',
                "application/json",
            ),
            "https://intern.avfroburger.test/api/v1/public/events/calendar.ics": (
                "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n",
                "text/calendar; charset=utf-8",
            ),
        }

        fetch_text_mock.side_effect = lambda url, timeout, accept="*/*": responses[url]

        stdout = StringIO()
        call_command("verify_wordpress_event_contract", stdout=stdout)

        output = stdout.getvalue()
        self.assertIn("WordPress contract check passed.", output)

    @override_settings(PUBLIC_EVENT_SOURCE_BASE_URL="https://intern.avfroburger.test")
    @patch("core.management.commands.verify_wordpress_event_contract.Command.fetch_text")
    def test_command_rejects_missing_required_field(self, fetch_text_mock):
        responses = {
            "https://intern.avfroburger.test/api/public/events/upcoming/": (
                '{"count": 1, "results": [{"id": 1, "title": "API Test Event", "slug": "api-test-event", "short_description": "Kurzbeschreibung", "start_at": "2026-07-24T18:00:00+02:00", "end_at": "2026-07-24T20:00:00+02:00", "timezone_name": "Europe/Zurich"}]}',
                "application/json",
            ),
        }

        def fake_fetch(url, timeout, accept="*/*"):
            if url in responses:
                return responses[url]
            if url.endswith("/calendar.ics"):
                return "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n", "text/calendar"
            if url.endswith("/api-test-event/"):
                return '{"id": 1, "title": "API Test Event", "slug": "api-test-event", "short_description": "Kurzbeschreibung", "start_at": "2026-07-24T18:00:00+02:00", "end_at": "2026-07-24T20:00:00+02:00", "timezone_name": "Europe/Zurich", "location_name": "Basel"}', "application/json"
            return '{"count": 0, "next": null, "previous": null, "results": []}', "application/json"

        fetch_text_mock.side_effect = fake_fetch

        with self.assertRaises(CommandError):
            call_command("verify_wordpress_event_contract")
