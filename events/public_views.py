import hashlib
import json
import re
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from accounts.models import CalendarSubscription

from . import signing
from .calendar_service import CalendarFeedService, CalendarResponseBuilder
from .models import Event, EventSignup, EventSignupColumn


SIGNUP_RATE_LIMIT_SECONDS = 15
PRIVATE_CALENDAR_RATE_LIMIT_WINDOW = 3600
PRIVATE_CALENDAR_RATE_LIMIT_MAX = 120


def _public_queryset():
    return Event.objects.filter(is_public=True, is_cancelled=False)


def _homepage_queryset():
    return _public_queryset().filter(show_on_homepage=True).exclude(status="INTERN")


def _event_to_payload(event):
    start_at = timezone.localtime(event.start)
    end_at = timezone.localtime(event.end)
    return {
        "id": event.pk,
        "title": event.title,
        "slug": event.slug,
        "short_description": event.short_description,
        "status": event.status,
        "status_label": event.get_status_display(),
        "start_at": start_at.isoformat(),
        "end_at": end_at.isoformat(),
        "timezone_name": event.timezone_name,
        "location_name": event.location,
        "detail_path": event.public_detail_path,
        "source_url": event.public_source_url,
        "calendar_ics_path": f"/calendar/public/events/{event.slug}.ics",
        "calendar_ics_url": f"{settings.PUBLIC_EVENT_SOURCE_BASE_URL}/calendar/public/events/{event.slug}.ics"
        if settings.PUBLIC_EVENT_SOURCE_BASE_URL
        else "",
    }


def _column_to_payload(column):
    return {
        "key": column.key,
        "label": column.label,
        "type": column.field_type,
        "required": column.is_required,
        "public": column.is_public,
        "sort_order": column.sort_order,
        "options": column.options,
        "placeholder": column.placeholder,
    }


def _serialize_public_value(column, value):
    if column.field_type == EventSignupColumn.FIELD_TYPE_CHECKBOX:
        return bool(value)
    if value is None:
        return ""
    return str(value)


def _detail_payload(event):
    payload = _event_to_payload(event)
    start_at = timezone.localtime(event.start)
    end_at = timezone.localtime(event.end)
    active_columns = list(event.active_signup_columns())
    public_columns = [column for column in active_columns if column.is_public]

    signups = []
    for signup in event.signups.public_visible().order_by("created_at", "pk"):
        values = {}
        for column in public_columns:
            values[column.key] = _serialize_public_value(column, signup.values.get(column.key))
        signups.append(
            {
                "vulgo": signup.vulgo,
                "attending": signup.attending,
                "created_at": timezone.localtime(signup.created_at).isoformat(),
                "values": values,
            }
        )

    payload.update(
        {
            "description": event.description,
            "date": start_at.date().isoformat(),
            "start_time": start_at.strftime("%H:%M"),
            "end_time": end_at.strftime("%H:%M"),
            "location": event.location,
            "image_url": None,
            "signup_enabled": event.signup_enabled,
            "signup_open": event.signup_enabled and not event.is_signup_closed,
            "signup_deadline": timezone.localtime(event.signup_deadline).isoformat(),
            "signup_columns": [_column_to_payload(column) for column in active_columns],
            "signups": signups,
        }
    )
    return payload


def _get_limit(request, default=20, maximum=60):
    raw = request.GET.get("limit")
    if raw is None:
        return default
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(maximum, limit))


def _get_offset(request):
    raw = request.GET.get("offset")
    if raw is None:
        return 0
    try:
        offset = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(0, offset)


def _build_list_response(request, queryset, *, include_pagination):
    limit = _get_limit(request)
    offset = _get_offset(request)
    total = queryset.count()
    objects = list(queryset[offset : offset + limit])
    results = [_event_to_payload(event) for event in objects]

    if not include_pagination:
        return JsonResponse({"count": total, "results": results})

    def build_page_url(new_offset):
        params = {"limit": limit, "offset": new_offset}
        return f"{request.build_absolute_uri(request.path)}?{urlencode(params)}"

    next_url = build_page_url(offset + limit) if offset + limit < total else None
    previous_url = build_page_url(max(0, offset - limit)) if offset > 0 else None

    return JsonResponse(
        {
            "count": total,
            "next": next_url,
            "previous": previous_url,
            "results": results,
        }
    )


def _client_ip(request):
    # deploy/nginx-avf-intern.conf sets X-Forwarded-For to
    # $proxy_add_x_forwarded_for, which APPENDS the real peer address after
    # whatever the client sent - the trustworthy value is therefore the LAST
    # entry, not the first (which a client can freely spoof).
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        parts = [part.strip() for part in forwarded_for.split(",") if part.strip()]
        if parts:
            return parts[-1]
    return request.META.get("REMOTE_ADDR", "unknown")


def _signup_cache_key(event_id, request):
    return f"public-event-signup:{event_id}:{_client_ip(request)}"


def _signup_throttled(event_id, request):
    return bool(cache.get(_signup_cache_key(event_id, request)))


def _mark_signup_attempt(event_id, request):
    cache.set(_signup_cache_key(event_id, request), True, timeout=SIGNUP_RATE_LIMIT_SECONDS)


def _private_calendar_cache_key(token_hash, request):
    return f"private-calendar-feed:{token_hash[:12]}:{_client_ip(request)}"


def _private_calendar_rate_limited(token_hash, request):
    key = _private_calendar_cache_key(token_hash, request)
    added = cache.add(key, 1, timeout=PRIVATE_CALENDAR_RATE_LIMIT_WINDOW)
    if added:
        return False
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=PRIVATE_CALENDAR_RATE_LIMIT_WINDOW)
        return False
    return count > PRIVATE_CALENDAR_RATE_LIMIT_MAX


def _error_response(code, message, status):
    return JsonResponse({"success": False, "code": code, "message": message}, status=status)


def _parse_request_payload(request):
    if request.content_type and request.content_type.startswith("application/json"):
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    values = {}
    payload = {}
    for key in request.POST:
        if len(request.POST.getlist(key)) != 1:
            return None
        if key.startswith("values[") and key.endswith("]"):
            values[key[7:-1]] = request.POST.get(key)
        else:
            # Keep unknown top-level fields for the same strict validation as JSON.
            payload[key] = request.POST.get(key)
    if values or payload.get("operation") != "read":
        payload["values"] = values
    return payload


def _parse_boolean(value):
    if value in (True, False):
        return value
    if isinstance(value, int):
        # JSON booleans may also arrive as 0/1. Other integers are not
        # boolean values and must not silently become True on the server.
        if value in (0, 1):
            return bool(value)
        return None
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"1", "true", "yes", "on", "ja"}:
            return True
        if raw in {"0", "false", "no", "off", "nein"}:
            return False
    return None


def _normalize_signup_payload(event, payload):
    if not isinstance(payload, dict):
        return None, ("invalid_payload", "Die Anmeldung konnte nicht verarbeitet werden.", 400)

    allowed_payload_keys = {"vulgo", "attending", "website", "values", "pin", "operation"}
    if set(payload) - allowed_payload_keys:
        return None, ("invalid_payload", "Die Anmeldung konnte nicht verarbeitet werden.", 400)

    raw_website = payload.get("website", "")
    if raw_website is not None and not isinstance(raw_website, str):
        return None, ("invalid_payload", "Die Anmeldung konnte nicht verarbeitet werden.", 400)
    website = (raw_website or "").strip()
    if website:
        return None, ("invalid_request", "Die Anmeldung konnte nicht verarbeitet werden.", 400)

    raw_vulgo = payload.get("vulgo", "")
    if not isinstance(raw_vulgo, str):
        return None, ("invalid_payload", "Die Anmeldung konnte nicht verarbeitet werden.", 400)
    vulgo = " ".join(raw_vulgo.split())
    if not vulgo:
        return None, ("missing_vulgo", "Bitte gib ein Vulgo an.", 400)
    if len(vulgo) > 80:
        return None, ("vulgo_too_long", "Das Vulgo ist zu lang.", 400)

    attending = _parse_boolean(payload.get("attending"))
    if attending is None:
        return None, ("missing_attending", "Bitte gib an, ob du anwesend bist.", 400)

    raw_values = payload.get("values", {})
    if raw_values is None:
        raw_values = {}
    if not isinstance(raw_values, dict):
        return None, ("invalid_values", "Die Zusatzfelder sind ungueltig.", 400)

    columns = {column.key: column for column in event.active_signup_columns()}
    unknown_fields = sorted(set(raw_values.keys()) - set(columns.keys()))
    if unknown_fields:
        return None, ("unknown_fields", "Die Zusatzfelder sind ungueltig.", 400)

    cleaned_values = {}
    for key, column in columns.items():
        raw_value = raw_values.get(key)
        if column.field_type == EventSignupColumn.FIELD_TYPE_CHECKBOX:
            if raw_value is None:
                value = False
            else:
                value = _parse_boolean(raw_value)
                if value is None:
                    return None, ("invalid_boolean", f'"{column.label}" ist ungültig.', 400)
            if column.is_required and not value:
                return None, ("required_field_missing", f'"{column.label}" ist ein Pflichtfeld.', 400)
            cleaned_values[key] = value
            continue

        if raw_value is not None and not isinstance(raw_value, str):
            return None, ("invalid_value", f'"{column.label}" ist ungültig.', 400)
        value = (raw_value or "").strip()
        max_length = 2000 if column.field_type == EventSignupColumn.FIELD_TYPE_TEXTAREA else 200
        if len(value) > max_length:
            return None, ("value_too_long", f'"{column.label}" ist zu lang.', 400)
        if column.is_required and not value:
            return None, ("required_field_missing", f'"{column.label}" ist ein Pflichtfeld.', 400)
        if column.field_type == EventSignupColumn.FIELD_TYPE_SELECT and value and value not in column.options:
            return None, ("invalid_choice", f'Fuer "{column.label}" wurde eine ungueltige Auswahl uebermittelt.', 400)
        cleaned_values[key] = value

    return {"vulgo": vulgo, "attending": attending, "values": cleaned_values}, None


def _signup_replay_cache_key(signature):
    return "public-event-signup-sig:" + hashlib.sha256(signature.encode("utf-8")).hexdigest()


def _authenticate_signup_request(request, slug):
    """Authenticates a signed signup POST and fails closed when unconfigured."""
    secret = settings.PUBLIC_EVENT_SIGNUP_SHARED_SECRET
    if not secret:
        return _error_response(
            "signup_unavailable",
            "Anmeldungen sind derzeit nicht verfuegbar.",
            503,
        )

    signature = request.headers.get(signing.SIGNATURE_HEADER, "")
    timestamp = request.headers.get(signing.TIMESTAMP_HEADER, "")
    if not signing.verify_signed_request(secret, slug, timestamp, request.body, signature):
        return _error_response("invalid_authentication", "Die Anmeldung konnte nicht verarbeitet werden.", 403)
    if not cache.add(_signup_replay_cache_key(signature), True, timeout=signing.DEFAULT_TOLERANCE_SECONDS * 2):
        return _error_response("invalid_authentication", "Die Anmeldung konnte nicht verarbeitet werden.", 403)

    return None


@require_safe
def legacy_upcoming_events_api(request):
    now = timezone.now()
    queryset = _homepage_queryset().filter(end__gte=now).order_by("start", "title")
    return _build_list_response(request, queryset, include_pagination=False)


@require_safe
def v1_upcoming_events_api(request):
    now = timezone.now()
    queryset = _public_queryset().filter(end__gte=now).order_by("start", "title")
    return _build_list_response(request, queryset, include_pagination=True)


@require_safe
def v1_past_events_api(request):
    now = timezone.now()
    queryset = _public_queryset().filter(end__lt=now).order_by("-start", "-title")
    return _build_list_response(request, queryset, include_pagination=True)


@require_safe
def v1_event_detail_api(request, slug):
    try:
        event = _public_queryset().prefetch_related("signup_columns", "signups").get(slug=slug)
    except Event.DoesNotExist as exc:
        raise Http404("Event not found.") from exc
    return JsonResponse(_detail_payload(event))


@csrf_exempt
@never_cache
def v1_event_signup_api(request, slug):
    if request.method != "POST":
        return _error_response("method_not_allowed", "Nur POST ist erlaubt.", 405)

    auth_error = _authenticate_signup_request(request, slug)
    if auth_error is not None:
        return auth_error

    try:
        # MariaDB cannot create the conditional unique constraint used for
        # soft-deleted signups. Locking the parent event serializes all
        # public signup checks for this event.
        with transaction.atomic():
            event = (
                _public_queryset()
                .select_for_update()
                .prefetch_related("signup_columns")
                .get(slug=slug)
            )

            # Re-check all mutable security state while the row is locked.
            if not event.signup_enabled:
                return _error_response("signup_disabled", "Fuer diesen Anlass sind keine Anmeldungen moeglich.", 409)
            if event.is_signup_closed:
                return _error_response("signup_closed", "Der Anmeldeschluss ist bereits abgelaufen.", 409)
            payload = _parse_request_payload(request)
            if not isinstance(payload, dict):
                return _error_response("invalid_payload", "Ungültige Anfrage.", 400)
            operation = payload.get("operation", "create")
            if operation in ("read", "update"):
                return _edit_signup(event, payload, operation)
            if operation != "create":
                return _error_response("invalid_payload", "Ungültige Anfrage.", 400)
            if _signup_throttled(event.pk, request):
                return _error_response("rate_limited", "Bitte warte kurz, bevor du das Formular erneut absendest.", 429)
            cleaned, error = _normalize_signup_payload(event, payload)
            if error is not None:
                code, message, status = error
                return _error_response(code, message, status)

            normalized_vulgo = EventSignup.normalize_vulgo(cleaned["vulgo"])
            if EventSignup.objects.filter(event=event, normalized_vulgo=normalized_vulgo).exists():
                return _error_response("duplicate_signup", "Fuer diesen Anlass besteht bereits eine Anmeldung mit diesem Vulgo.", 409)

            pin = payload.get("pin")
            if not isinstance(pin, str) or re.fullmatch(r"[0-9]{4,6}", pin) is None:
                return _error_response("invalid_pin", "Der PIN muss aus 4 bis 6 Ziffern bestehen.", 400)

            signup = EventSignup(
                event=event,
                vulgo=cleaned["vulgo"],
                attending=cleaned["attending"],
                values=cleaned["values"],
            )
            signup.set_pin(pin)
            signup.save(source=EventSignup.SOURCE_API)
    except Event.DoesNotExist:
        return _error_response("event_not_found", "Dieser Anlass wurde nicht gefunden.", 404)
    except IntegrityError:
        return _error_response("duplicate_signup", "Fuer diesen Anlass besteht bereits eine Anmeldung mit diesem Vulgo.", 409)

    _mark_signup_attempt(event.pk, request)

    return JsonResponse(
        {
            "success": True,
            "code": "signup_created",
            "message": "Die Anmeldung wurde erfolgreich gespeichert.",
            "signup": {
                "vulgo": signup.vulgo,
                "attending": signup.attending,
            },
        },
        status=201,
    )


def _edit_signup(event, payload, operation):
    """Called inside the event transaction; never exposes PINs or hashes."""
    allowed = {"operation", "vulgo", "pin", "website"}
    if operation == "update":
        allowed |= {"attending", "values"}
    vulgo, pin = payload.get("vulgo"), payload.get("pin")
    if (set(payload) - allowed or not isinstance(vulgo, str) or len(vulgo) > 80
            or not isinstance(pin, str) or re.fullmatch(r"[0-9]{4,6}", pin) is None
            or payload.get("website", "")):
        return _error_response("invalid_credentials", "Vulgo oder PIN ungültig. PIN vergessen? Bitte kontaktiere den Admin.", 403)
    signup = event.signups.select_for_update().filter(
        normalized_vulgo=EventSignup.normalize_vulgo(vulgo)
    ).first()
    now = timezone.now()
    if signup and signup.pin_locked_until and signup.pin_locked_until > now:
        return _error_response("pin_locked", "Zu viele Fehlversuche. Bitte versuche es in 15 Minuten erneut oder kontaktiere den Admin.", 429)
    if not signup or not signup.pin_hash or not check_password(pin, signup.pin_hash):
        if signup and signup.pin_hash:
            attempts = 0 if signup.pin_locked_until else signup.pin_failed_attempts
            attempts += 1
            EventSignup.objects.filter(pk=signup.pk).update(
                pin_failed_attempts=attempts,
                pin_locked_until=now + timedelta(minutes=15) if attempts >= 5 else None,
            )
        return _error_response("invalid_credentials", "Vulgo oder PIN ungültig. PIN vergessen? Bitte kontaktiere den Admin.", 403)
    EventSignup.objects.filter(pk=signup.pk).update(pin_failed_attempts=0, pin_locked_until=None)
    signup.pin_failed_attempts = 0
    signup.pin_locked_until = None
    if operation == "update":
        cleaned, error = _normalize_signup_payload(event, payload)
        if error:
            return _error_response(*error)
        signup.attending = cleaned["attending"]
        # Retain data for columns that an administrator has deactivated.
        signup.values = {**signup.values, **cleaned["values"]}
        signup.save(source=EventSignup.SOURCE_API)
    keys = {column.key for column in event.active_signup_columns()}
    return JsonResponse({
        "success": True,
        "code": "signup_updated" if operation == "update" else "signup_loaded",
        "signup": {"vulgo": signup.vulgo, "attending": signup.attending,
                   "values": {key: value for key, value in signup.values.items() if key in keys}},
    })


@require_safe
def v1_calendar_feed(request):
    service = CalendarFeedService()
    result = service.build_public_feed()
    return CalendarResponseBuilder().build(
        request,
        result,
        filename="av-froburger.ics",
        cache_control="public, max-age=300",
    )


@require_safe
def public_calendar_feed(request):
    return v1_calendar_feed(request)


@require_safe
def public_event_calendar(request, slug):
    try:
        event = Event.objects.get(slug=slug, is_public=True)
    except Event.DoesNotExist as exc:
        raise Http404("Event not found.") from exc

    service = CalendarFeedService()
    result = service.build_single_event_calendar(event, visibility="public")
    return CalendarResponseBuilder().build(
        request,
        result,
        filename=service.serializer.event_filename(event),
        cache_control="public, max-age=300",
    )


@require_safe
def private_calendar_feed(request, token):
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        subscription = CalendarSubscription.objects.select_related("user").get(token_hash=token_hash, revoked_at__isnull=True)
    except CalendarSubscription.DoesNotExist as exc:
        raise Http404("Calendar subscription not found.") from exc

    if not subscription.user.is_active:
        raise Http404("Calendar subscription not found.")

    if _private_calendar_rate_limited(token_hash, request):
        return HttpResponse(status=429)

    service = CalendarFeedService()
    result = service.build_private_feed(subscription)
    CalendarSubscription.objects.filter(pk=subscription.pk).update(last_used_at=timezone.now())
    return CalendarResponseBuilder().build(
        request,
        result,
        filename="av-froburger-intern.ics",
        cache_control="private, max-age=300",
    )
