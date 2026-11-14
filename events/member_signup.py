"""Server-side policy for public registrations to internal events."""
import hashlib
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from accounts.models import Profile
from .models import EventSignup, SignupAttemptWindow

DENIED_MESSAGE = "Sorry, nur für Froburger."
MEMBER_ROLES = {"FUX", "BURSCH", "SENIOR", "CONSENIOR", "FUXMAJOR", "AKTUAR", "QUAESTOR", "ALTFROBURGER"}


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
        if window.expires_at <= now:
            window.attempts = 0
            window.expires_at = now + timedelta(minutes=10)
        if window.attempts >= 20:
            return False
        window.attempts += 1
        window.save(update_fields=["attempts", "expires_at"])
    SignupAttemptWindow.objects.filter(expires_at__lt=now - timedelta(days=1)).delete()
    return True
