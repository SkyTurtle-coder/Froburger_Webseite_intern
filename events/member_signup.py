"""Server-side policy for public registrations to internal events."""
import hashlib
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import Profile
from .models import EventSignup, SignupAttemptWindow

DENIED_MESSAGE = "Sorry, nur für Froburger."
MEMBER_ROLES = {"FUX", "BURSCH", "SENIOR", "CONSENIOR", "FUXMAJOR", "AKTUAR", "QUAESTOR", "ALTFROBURGER"}
BLOCK_SECONDS = (30, 60, 120, 300, 600, 1800, 3600, 7200, 21600, 43200, 86400)
FAILURE_THRESHOLD = 5
ATTEMPT_LIMIT = 120


def is_internal(event):
    return event.is_internal or event.status == "INTERN"


def resolve_member(vulgo):
    if not isinstance(vulgo, str) or not vulgo.strip() or len(vulgo) > 80:
        return None
    normalized = EventSignup.normalize_vulgo(vulgo)
    # Use the same Unicode/whitespace normalization as signups, independently
    # of database collation. Ambiguous vulgos must never select an arbitrary user.
    matches = [pk for pk, value in Profile.objects.values_list("pk", "vulgo")
               if EventSignup.normalize_vulgo(value) == normalized]
    if len(matches) != 1:
        return None
    member = Profile.objects.select_related("user").get(pk=matches[0])
    if (not member.user.is_active or member.death_date or member.exit_year
            or member.exit_semester or not member.roles.filter(code__in=MEMBER_ROLES).exists()):
        return None
    return member


def attempt_allowed(client_key):
    """Database-backed, shared between workers; count failures and successes.

    One window across events and operations prevents switching slugs or vulgos
    from resetting the limit. Keys contain no raw IP address or member name.
    """
    key = hashlib.sha256(client_key.encode()).hexdigest()
    now = timezone.now()
    with transaction.atomic():
        SignupAttemptWindow.objects.get_or_create(key=key, defaults={"expires_at": now})
        window = SignupAttemptWindow.objects.select_for_update().get(key=key)
        if window.blocked_until and window.blocked_until > now:
            # Requests during a lock neither query members nor extend the lock.
            return False
        if window.penalty_reset_at and window.penalty_reset_at <= now:
            window.failed_attempts = 0
            window.penalty_level = 0
            window.blocked_until = None
            window.penalty_reset_at = None
        if window.expires_at <= now:
            window.attempts = 0
            window.expires_at = now + timedelta(minutes=10)
        if window.attempts >= ATTEMPT_LIMIT:
            return False
        window.attempts += 1
        window.save()
    SignupAttemptWindow.objects.filter(expires_at__lt=now - timedelta(days=1)).filter(
        Q(penalty_reset_at__isnull=True) | Q(penalty_reset_at__lte=now)
    ).delete()
    return True


def record_failure(client_key):
    """Count all indistinguishable denials, not only unknown member names.

    Otherwise lock behaviour would itself become a membership oracle. A valid
    attempt does not erase history; reset after 24 hours without failures,
    measured from the end of the last block when one was imposed.
    """
    key = hashlib.sha256(client_key.encode()).hexdigest()
    now = timezone.now()
    with transaction.atomic():
        SignupAttemptWindow.objects.get_or_create(key=key, defaults={"expires_at": now})
        window = SignupAttemptWindow.objects.select_for_update().get(key=key)
        if window.blocked_until and window.blocked_until > now:
            return
        if window.penalty_reset_at and window.penalty_reset_at <= now:
            window.failed_attempts = 0
            window.penalty_level = 0
        window.failed_attempts += 1
        window.penalty_reset_at = now + timedelta(days=1)
        if window.failed_attempts >= FAILURE_THRESHOLD:
            duration = BLOCK_SECONDS[min(window.penalty_level, len(BLOCK_SECONDS) - 1)]
            window.blocked_until = now + timedelta(seconds=duration)
            window.penalty_level = min(window.penalty_level + 1, len(BLOCK_SECONDS))
            window.failed_attempts = 0
            window.penalty_reset_at = window.blocked_until + timedelta(days=1)
        window.save()
