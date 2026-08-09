from io import StringIO
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from config.settings import env_bool, is_secret_key_acceptable
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


class SettingsFailSafeGuardTests(TestCase):
    """SEC-003 / SEC-015: an incomplete production environment must never
    silently resolve to an insecure default."""

    def test_debug_defaults_to_false_when_env_var_is_missing(self):
        self.assertFalse(env_bool("DJANGO_DEBUG_DOES_NOT_EXIST_IN_ENV", False))

    def test_debug_env_var_explicit_values_still_respected(self):
        import os

        os.environ["DJANGO_DEBUG_TEST_TRUE"] = "True"
        os.environ["DJANGO_DEBUG_TEST_FALSE"] = "False"
        try:
            self.assertTrue(env_bool("DJANGO_DEBUG_TEST_TRUE", False))
            self.assertFalse(env_bool("DJANGO_DEBUG_TEST_FALSE", True))
        finally:
            del os.environ["DJANGO_DEBUG_TEST_TRUE"]
            del os.environ["DJANGO_DEBUG_TEST_FALSE"]

    def test_known_placeholders_are_rejected(self):
        for placeholder in (
            "change-me",
            "django-insecure-change-me",
            "replace-with-strong-secret",
            "replace-with-local-secret",
        ):
            self.assertFalse(is_secret_key_acceptable(placeholder), placeholder)

    def test_django_startproject_style_placeholder_is_rejected(self):
        self.assertFalse(is_secret_key_acceptable("django-insecure-abcdefghijklmnopqrstuvwxyz"))

    def test_implausibly_short_key_is_rejected(self):
        self.assertFalse(is_secret_key_acceptable("short-key-123"))

    def test_empty_key_is_rejected(self):
        self.assertFalse(is_secret_key_acceptable(""))

    def test_a_real_generated_key_is_accepted(self):
        from django.core.management.utils import get_random_secret_key

        self.assertTrue(is_secret_key_acceptable(get_random_secret_key()))


class ContentSecurityPolicyReportOnlyTests(TestCase):
    """SEC-017: the CSP is deployed Report-Only - it must never appear as an
    enforcing header, on any response, until that's a deliberate decision."""

    def test_report_only_header_present_on_a_public_page(self):
        response = self.client.get("/healthz/")
        self.assertIn("Content-Security-Policy-Report-Only", response.headers)

    def test_never_sends_an_enforcing_csp_header(self):
        response = self.client.get("/healthz/")
        # Header lookups are case-insensitive and "Content-Security-Policy"
        # is a prefix of "Content-Security-Policy-Report-Only" - checking
        # for exact equality against the response's actual header names
        # avoids a false pass if a substring check were used instead.
        header_names = {name.lower() for name in response.headers.keys()}
        self.assertNotIn("content-security-policy", header_names)
        self.assertIn("content-security-policy-report-only", header_names)
