from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_safe

from .public_members import build_public_members_payload
from .throttling import client_ip

# SEC-013: this endpoint is intentionally public (WordPress's own member
# directory pulls it with no auth by design) - this moderate per-IP limit is
# only to blunt bulk scraping directly against Django, bypassing WordPress
# entirely. Generous enough that WordPress's own periodic sync is never at
# risk of being throttled (it caches responses for minutes at a time, see
# avf_events_cache_ttl on the WordPress side).
PUBLIC_MEMBERS_RATE_LIMIT_MAX = 30
PUBLIC_MEMBERS_RATE_LIMIT_WINDOW_SECONDS = 60


def _public_members_rate_limited(request):
    key = f"public-members-api:{client_ip(request)}"
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=PUBLIC_MEMBERS_RATE_LIMIT_WINDOW_SECONDS)
        return False
    return count > PUBLIC_MEMBERS_RATE_LIMIT_MAX


@require_safe
def v1_public_members_api(request):
    if _public_members_rate_limited(request):
        return JsonResponse({"detail": "Rate limit exceeded."}, status=429)
    return JsonResponse(build_public_members_payload())
