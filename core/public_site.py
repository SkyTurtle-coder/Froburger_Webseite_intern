import logging
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache


logger = logging.getLogger(__name__)

PUBLIC_SITE_CACHE_KEY = "core.public_site_url"
PRIMARY_CACHE_TTL_SECONDS = 60
FALLBACK_CACHE_TTL_SECONDS = 30
HEALTHCHECK_TIMEOUT_SECONDS = 1.75
SUCCESS_STATUSES = {200, 301, 302, 303, 307, 308}


def normalize_public_site_url(url):
    value = (url or "").strip()
    if not value:
        return ""
    return f"{value.rstrip('/')}/"


def get_public_site_primary_url():
    return normalize_public_site_url(
        getattr(settings, "PUBLIC_WEBSITE_PRIMARY_URL", "https://test.avfroburger.ch/")
    )


def get_public_site_fallback_url():
    return normalize_public_site_url(
        getattr(settings, "PUBLIC_WEBSITE_FALLBACK_URL", "https://avfroburger.ch/")
    )


def get_public_site_url():
    cached = cache.get(PUBLIC_SITE_CACHE_KEY)
    if cached:
        return cached

    primary_url = get_public_site_primary_url()
    fallback_url = get_public_site_fallback_url()

    if primary_url and is_public_site_reachable(primary_url):
        cache.set(PUBLIC_SITE_CACHE_KEY, primary_url, PRIMARY_CACHE_TTL_SECONDS)
        return primary_url

    cache.set(PUBLIC_SITE_CACHE_KEY, fallback_url, FALLBACK_CACHE_TTL_SECONDS)
    return fallback_url


def is_public_site_reachable(url):
    if not url:
        return False

    parsed = urlparse(url)
    expected_host = parsed.netloc.casefold()
    request = Request(url, method="HEAD")

    try:
        with urlopen(request, timeout=HEALTHCHECK_TIMEOUT_SECONDS) as response:
            status_code = getattr(response, "status", None) or response.getcode()
            final_host = urlparse(response.geturl()).netloc.casefold()
            return status_code in SUCCESS_STATUSES and final_host == expected_host
    except HTTPError as exc:
        if exc.code in SUCCESS_STATUSES:
            final_host = urlparse(exc.geturl() or url).netloc.casefold()
            return final_host == expected_host
        return False
    except (URLError, TimeoutError, ValueError) as exc:
        logger.warning("Public site healthcheck failed: %s", exc.__class__.__name__)
        return False
