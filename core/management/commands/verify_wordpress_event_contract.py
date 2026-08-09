import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from events.models import Event


REQUIRED_EVENT_FIELDS = (
    "id",
    "title",
    "slug",
    "short_description",
    "start_at",
    "end_at",
    "timezone_name",
    "location_name",
)


class Command(BaseCommand):
    help = "Prüft den öffentlichen Event-API-Vertrag gegen die WordPress-Erwartungen."

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-url",
            help="Öffentliche Basis-URL der Django-Instanz, z. B. https://intern.avfroburger.ch",
        )
        parser.add_argument(
            "--slug",
            help="Slug eines öffentlichen Events für den Detail-Endpunkt. Standard: erstes öffentliches Event aus der Datenbank.",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=8,
            help="HTTP-Timeout in Sekunden. Standard: 8",
        )

    def handle(self, *args, **options):
        base_url = (options["base_url"] or settings.PUBLIC_EVENT_SOURCE_BASE_URL).rstrip("/")
        if not base_url:
            raise CommandError("Set PUBLIC_EVENT_SOURCE_BASE_URL or pass --base-url.")

        slug = options["slug"] or Event.objects.filter(is_public=True).order_by("start", "title").values_list("slug", flat=True).first()
        if not slug:
            raise CommandError("No public event available. Create at least one Event with is_public=True or pass --slug.")

        timeout = max(1, int(options["timeout"]))
        page_path = f"/{settings.PUBLIC_EVENT_DETAIL_PATH_PREFIX.strip('/')}/"

        legacy_url = f"{base_url}/api/public/events/upcoming/"
        upcoming_url = f"{base_url}/api/v1/public/events/upcoming/"
        past_url = f"{base_url}/api/v1/public/events/past/"
        detail_url = f"{base_url}/api/v1/public/events/{slug}/"
        calendar_url = f"{base_url}/api/v1/public/events/calendar.ics"

        self.stdout.write("Checking WordPress event API contract")
        self.stdout.write(f"Base URL: {base_url}")
        self.stdout.write(f"Recommended API endpoint: {legacy_url}")
        self.stdout.write(f"Recommended API base v1: {base_url}/api/v1/public/")
        self.stdout.write(f"Recommended page path: {page_path}")
        self.stdout.write(f"Detail slug: {slug}")

        legacy_payload = self.fetch_json(legacy_url, timeout)
        self.validate_list_payload("legacy upcoming", legacy_payload, include_pagination=False)
        self.stdout.write(self.style.SUCCESS(f"OK legacy upcoming: {legacy_url}"))

        upcoming_payload = self.fetch_json(upcoming_url, timeout)
        self.validate_list_payload("v1 upcoming", upcoming_payload, include_pagination=True)
        self.stdout.write(self.style.SUCCESS(f"OK v1 upcoming: {upcoming_url}"))

        past_payload = self.fetch_json(past_url, timeout)
        self.validate_list_payload("v1 past", past_payload, include_pagination=True)
        self.stdout.write(self.style.SUCCESS(f"OK v1 past: {past_url}"))

        detail_payload = self.fetch_json(detail_url, timeout)
        self.validate_event_payload("v1 detail", detail_payload)
        self.stdout.write(self.style.SUCCESS(f"OK v1 detail: {detail_url}"))

        calendar_content, calendar_type = self.fetch_text(calendar_url, timeout)
        self.validate_calendar_payload(calendar_content, calendar_type)
        self.stdout.write(self.style.SUCCESS(f"OK calendar feed: {calendar_url}"))

        self.stdout.write(self.style.SUCCESS("WordPress contract check passed."))

    def fetch_json(self, url, timeout):
        body, content_type = self.fetch_text(url, timeout, accept="application/json")
        if "json" not in content_type.lower():
            raise CommandError(f"{url} returned unexpected Content-Type: {content_type}")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise CommandError(f"{url} returned invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise CommandError(f"{url} must return a JSON object.")
        return payload

    def fetch_text(self, url, timeout, accept="*/*"):
        request = Request(url, headers={"Accept": accept, "User-Agent": "django-wordpress-contract-check/1.0"})
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                content_type = response.headers.get("Content-Type", "")
                return body, content_type
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise CommandError(f"{url} returned HTTP {exc.code}: {detail[:200]}") from exc
        except URLError as exc:
            raise CommandError(f"{url} could not be reached: {exc.reason}") from exc

    def validate_list_payload(self, label, payload, *, include_pagination):
        required_keys = {"count", "results"}
        missing_keys = required_keys - payload.keys()
        if missing_keys:
            missing = ", ".join(sorted(missing_keys))
            raise CommandError(f"{label} is missing keys: {missing}")

        if include_pagination:
            for key in ("next", "previous"):
                if key not in payload:
                    raise CommandError(f"{label} is missing pagination key: {key}")
        else:
            for key in ("next", "previous"):
                if key in payload:
                    raise CommandError(f"{label} must not contain pagination key: {key}")

        if not isinstance(payload["count"], int):
            raise CommandError(f"{label} count must be an integer.")
        if not isinstance(payload["results"], list):
            raise CommandError(f"{label} results must be a list.")

        for item in payload["results"]:
            self.validate_event_payload(label, item)

    def validate_event_payload(self, label, payload):
        if not isinstance(payload, dict):
            raise CommandError(f"{label} must return an object.")

        missing = [field for field in REQUIRED_EVENT_FIELDS if field not in payload]
        if missing:
            raise CommandError(f"{label} is missing event fields: {', '.join(missing)}")

        for field in REQUIRED_EVENT_FIELDS:
            value = payload[field]
            if value is None:
                raise CommandError(f"{label} field {field} must not be null.")
            if not isinstance(value, (str, int)):
                raise CommandError(f"{label} field {field} must be scalar.")
            if str(value).strip() == "":
                raise CommandError(f"{label} field {field} must not be empty.")

        for field in ("detail_path", "source_url"):
            if field in payload and payload[field] is not None and not isinstance(payload[field], str):
                raise CommandError(f"{label} optional field {field} must be a string.")

    def validate_calendar_payload(self, content, content_type):
        if "text/calendar" not in content_type.lower():
            raise CommandError(f"calendar feed returned unexpected Content-Type: {content_type}")
        for marker in ("BEGIN:VCALENDAR", "END:VCALENDAR", "BEGIN:VEVENT"):
            if marker not in content:
                raise CommandError(f"calendar feed is missing marker: {marker}")
