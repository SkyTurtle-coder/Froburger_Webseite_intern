import hashlib
import re
from dataclasses import dataclass
from datetime import date, timedelta, timezone as dt_timezone
from email.utils import parsedate_to_datetime
from html import unescape
from zoneinfo import ZoneInfo

from django.conf import settings
from django.http import HttpResponse, HttpResponseNotAllowed
from django.urls import reverse
from django.utils import timezone

from icalendar import Calendar, Event as ICalendarEvent

from accounts.models import CalendarSubscription

from .models import Event, EventCalendarTombstone


ZURICH = ZoneInfo("Europe/Zurich")


@dataclass
class CalendarRenderResult:
    body: bytes
    etag: str
    last_modified: timezone.datetime


class CalendarEventSerializer:
    def event_uid(self, event):
        return event.calendar_uid

    def event_url(self, event):
        return event.public_source_url

    def event_filename(self, event):
        return f"{event.slug or event.pk}.ics"

    def to_component(self, event, *, visibility):
        component = ICalendarEvent()
        component.add("uid", self.event_uid(event))
        component.add("dtstamp", self._dtstamp_for(event))
        component.add("last-modified", timezone.localtime(event.updated_at, dt_timezone.utc))
        component.add("sequence", int(event.calendar_sequence))
        component.add("summary", event.title)
        component.add("status", "CANCELLED" if getattr(event, "is_cancelled", False) else "CONFIRMED")
        component.add("class", "PUBLIC" if visibility == "public" else "PRIVATE")
        component.add("transp", "OPAQUE")

        self._add_time_fields(component, event.start, event.end)

        description = self._description_for(event, visibility=visibility)
        if description:
            component.add("description", description)

        if event.location:
            component.add("location", event.location)

        event_url = self.event_url(event)
        if event_url:
            component.add("url", event_url)

        return component

    def tombstone_to_component(self, tombstone, *, visibility):
        component = ICalendarEvent()
        component.add("uid", tombstone.calendar_uid)
        component.add("dtstamp", timezone.localtime(tombstone.created_at, dt_timezone.utc))
        component.add("last-modified", timezone.localtime(tombstone.updated_at, dt_timezone.utc))
        component.add("sequence", int(tombstone.calendar_sequence))
        component.add("summary", tombstone.title or "Abgesagter Anlass")
        component.add("status", "CANCELLED")
        component.add("class", "PUBLIC" if visibility == "public" else "PRIVATE")
        component.add("transp", "OPAQUE")

        if tombstone.start and tombstone.end:
            self._add_time_fields(component, tombstone.start, tombstone.end)

        if tombstone.location:
            component.add("location", tombstone.location)

        description = self._normalize_plain_text(tombstone.description)
        if description:
            component.add("description", description)

        return component

    def _add_time_fields(self, component, start, end):
        localized_start = timezone.localtime(start, ZURICH)
        localized_end = timezone.localtime(end, ZURICH)

        if self._is_all_day(localized_start, localized_end):
            component.add("dtstart", localized_start.date())
            component.add("dtend", localized_end.date() + timedelta(days=1))
            return

        component.add("dtstart", localized_start)
        component.add("dtend", localized_end)

    def _is_all_day(self, start, end):
        return (
            start.time().hour == 0
            and start.time().minute == 0
            and start.time().second == 0
            and end.time().hour == 0
            and end.time().minute == 0
            and end.time().second == 0
            and end.date() >= start.date()
        )

    def _dtstamp_for(self, event):
        base = event.created_at or event.updated_at or timezone.now()
        return timezone.localtime(base, dt_timezone.utc)

    def _description_for(self, event, *, visibility):
        if visibility == "public":
            return self._normalize_plain_text(event.short_description or event.description or event.title)
        return self._normalize_plain_text(event.description or event.short_description or event.title)

    def _normalize_plain_text(self, value):
        text = unescape(re.sub(r"<[^>]+>", " ", value or ""))
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        text = re.sub(r"\r\n?", "\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


class CalendarFeedService:
    def __init__(self):
        self.serializer = CalendarEventSerializer()

    def build_single_event_calendar(self, event, *, visibility):
        return self._render_calendar(
            name="AV Froburger",
            description="Anlass der AV Froburger",
            source_url=self._public_feed_url() if visibility == "public" else "",
            events=[self.serializer.to_component(event, visibility=visibility)],
            last_modified=event.updated_at,
        )

    def build_public_feed(self):
        events = list(self.public_events())
        tombstones = list(self.public_tombstones())
        components = [self.serializer.to_component(event, visibility="public") for event in events]
        components.extend(self.serializer.tombstone_to_component(tombstone, visibility="public") for tombstone in tombstones)
        last_modified = self._max_last_modified(
            [event.updated_at for event in events] + [tombstone.updated_at for tombstone in tombstones]
        )
        return self._render_calendar(
            name="AV Froburger",
            description="Anlässe der AV Froburger",
            source_url=self._public_feed_url(),
            events=components,
            last_modified=last_modified,
        )

    def build_private_feed(self, subscription):
        events = list(self.private_events_for_subscription(subscription))
        tombstones = list(self.private_tombstones())
        components = [self.serializer.to_component(event, visibility="private") for event in events]
        components.extend(self.serializer.tombstone_to_component(tombstone, visibility="private") for tombstone in tombstones)
        last_modified = self._max_last_modified(
            [event.updated_at for event in events] + [tombstone.updated_at for tombstone in tombstones]
        )
        return self._render_calendar(
            name="AV Froburger intern",
            description="Interne und öffentliche Anlässe der AV Froburger",
            source_url="",
            events=components,
            last_modified=last_modified,
        )

    def public_events(self):
        now = timezone.now()
        past_cutoff = now - timedelta(days=int(getattr(settings, "CALENDAR_PAST_RETENTION_DAYS", 90)))
        future_cutoff = now + timedelta(days=int(getattr(settings, "CALENDAR_FUTURE_HORIZON_DAYS", 730)))
        return (
            Event.objects.filter(is_public=True)
            .filter(start__lte=future_cutoff)
            .filter(end__gte=past_cutoff)
            .order_by("start", "title", "pk")
        )

    def private_events_for_subscription(self, subscription):
        if not subscription.is_active:
            return Event.objects.none()

        now = timezone.now()
        past_cutoff = now - timedelta(days=int(getattr(settings, "CALENDAR_PAST_RETENTION_DAYS", 90)))
        future_cutoff = now + timedelta(days=int(getattr(settings, "CALENDAR_FUTURE_HORIZON_DAYS", 730)))
        return Event.objects.filter(start__lte=future_cutoff, end__gte=past_cutoff).order_by("start", "title", "pk")

    def public_tombstones(self):
        return EventCalendarTombstone.objects.filter(was_public=True, expires_at__gte=timezone.now()).order_by("start", "calendar_uid")

    def private_tombstones(self):
        return EventCalendarTombstone.objects.filter(expires_at__gte=timezone.now()).order_by("start", "calendar_uid")

    def create_subscription(self, user):
        return CalendarSubscription.issue_for_user(user)

    def subscription_url(self, request, raw_token):
        return request.build_absolute_uri(reverse("private-calendar-feed", kwargs={"token": raw_token}))

    def _render_calendar(self, *, name, description, source_url, events, last_modified):
        calendar = Calendar()
        calendar.add("prodid", "-//AV Froburger//Anlasskalender//DE")
        calendar.add("version", "2.0")
        calendar.add("calscale", "GREGORIAN")
        calendar.add("method", "PUBLISH")
        calendar.add("x-wr-calname", name)
        calendar.add("x-wr-timezone", "Europe/Zurich")
        calendar.add("description", description)
        if source_url:
            calendar.add("source", source_url)

        for component in events:
            calendar.add_component(component)

        body = calendar.to_ical()
        etag = '"' + hashlib.sha256(body).hexdigest() + '"'
        return CalendarRenderResult(
            body=body,
            etag=etag,
            last_modified=timezone.localtime(last_modified or timezone.now(), dt_timezone.utc),
        )

    def _max_last_modified(self, values):
        cleaned = [value for value in values if value is not None]
        return max(cleaned) if cleaned else timezone.now()

    def _public_feed_url(self):
        configured = getattr(settings, "CALENDAR_PUBLIC_FEED_URL", "").strip()
        return configured


class CalendarResponseBuilder:
    def build(self, request, render_result, *, filename, cache_control):
        if request.method not in {"GET", "HEAD"}:
            return HttpResponseNotAllowed(["GET", "HEAD"])

        if self._matches_etag(request, render_result.etag) or self._not_modified_since(request, render_result.last_modified):
            response = HttpResponse(status=304)
        else:
            content = b"" if request.method == "HEAD" else render_result.body
            response = HttpResponse(content, content_type="text/calendar; charset=utf-8")

        response["ETag"] = render_result.etag
        response["Last-Modified"] = self._http_date(render_result.last_modified)
        response["Cache-Control"] = cache_control
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response

    def _matches_etag(self, request, etag):
        incoming = request.headers.get("If-None-Match", "").strip()
        return bool(incoming) and incoming == etag

    def _not_modified_since(self, request, last_modified):
        raw = request.headers.get("If-Modified-Since", "").strip()
        if not raw:
            return False
        try:
            header_time = parsedate_to_datetime(raw)
        except (TypeError, ValueError, IndexError):
            return False
        if header_time.tzinfo is None:
            header_time = header_time.replace(tzinfo=dt_timezone.utc)
        last_modified = timezone.localtime(last_modified, dt_timezone.utc).replace(microsecond=0)
        return header_time >= last_modified

    def _http_date(self, value):
        return timezone.localtime(value, dt_timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
