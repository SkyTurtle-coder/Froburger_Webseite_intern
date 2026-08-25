"""Login rate limiting (SEC-002).

Two independent, cache-based counters - never an in-process Python variable,
so this works correctly if the deployment ever runs multiple worker
processes behind a shared cache backend (Redis/Memcached); with Django's
default LocMemCache it still works correctly for this project's current
single-process uvicorn deployment (see deploy/avf-intern.service).

- Per client IP: catches one source spraying attempts across many accounts.
- Per normalized identifier (email/vulgo), independent of IP: catches
  distributed credential stuffing against a single account. Its cooldown is
  short and hard-capped by cache TTL (never extended by further attempts
  while it's active) specifically so it can never become a de-facto
  permanent lock an attacker could use to deny a real member access to
  their own account by deliberately failing their login.

Both counters reset naturally when their window expires. A successful login
clears the identifier-level counter for that identifier only - the IP-level
counter is deliberately left alone, otherwise an attacker spraying many
accounts from one IP could reset their own throttle by logging into one
account they legitimately know and then continue spraying the rest.
"""
from django.core.cache import cache

IP_MAX_ATTEMPTS = 15
IP_WINDOW_SECONDS = 600
IP_COOLDOWN_SECONDS = 600

IDENTIFIER_MAX_ATTEMPTS = 8
IDENTIFIER_WINDOW_SECONDS = 600
IDENTIFIER_COOLDOWN_SECONDS = 60

RESET_IP_MAX_ATTEMPTS = 12
RESET_IP_WINDOW_SECONDS = 1800
RESET_IP_COOLDOWN_SECONDS = 1800

RESET_IDENTIFIER_MAX_ATTEMPTS = 3
RESET_IDENTIFIER_WINDOW_SECONDS = 1800
RESET_IDENTIFIER_COOLDOWN_SECONDS = 1800


def client_ip(request):
    """Best-effort client IP, trusting only the hop nginx itself appends.

    deploy/nginx-avf-intern.conf sets `X-Forwarded-For $proxy_add_x_forwarded_for`,
    which APPENDS the real peer address after whatever the client already
    sent - so the trustworthy value is the LAST entry, not the first (the
    first is attacker-controlled). Only valid because nginx is the sole
    reverse proxy in front of Django here (single-hop trust).
    """
    if request is None:
        return "unknown"
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        parts = [part.strip() for part in forwarded_for.split(",") if part.strip()]
        if parts:
            return parts[-1]
    return request.META.get("REMOTE_ADDR", "unknown")


def _attempts_key(kind, value):
    return f"login-throttle:{kind}:attempts:{value}"


def _cooldown_key(kind, value):
    return f"login-throttle:{kind}:cooldown:{value}"


def _reset_attempts_key(kind, value):
    return f"password-reset-throttle:{kind}:attempts:{value}"


def _reset_cooldown_key(kind, value):
    return f"password-reset-throttle:{kind}:cooldown:{value}"


def _is_blocked(kind, value):
    return bool(cache.get(_cooldown_key(kind, value)))


def _register_failure(kind, value, window_seconds, max_attempts, cooldown_seconds):
    key = _attempts_key(kind, value)
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=window_seconds)
        count = 1
    if count >= max_attempts:
        cache.set(_cooldown_key(kind, value), True, timeout=cooldown_seconds)


def is_throttled(request, identifier):
    ip = client_ip(request)
    return _is_blocked("ip", ip) or (bool(identifier) and _is_blocked("id", identifier))


def register_failed_attempt(request, identifier):
    ip = client_ip(request)
    _register_failure("ip", ip, IP_WINDOW_SECONDS, IP_MAX_ATTEMPTS, IP_COOLDOWN_SECONDS)
    if identifier:
        _register_failure("id", identifier, IDENTIFIER_WINDOW_SECONDS, IDENTIFIER_MAX_ATTEMPTS, IDENTIFIER_COOLDOWN_SECONDS)


def clear_attempts_for_identifier(identifier):
    if not identifier:
        return
    cache.delete(_attempts_key("id", identifier))
    cache.delete(_cooldown_key("id", identifier))


def _normalize_reset_identifier(value):
    return " ".join((value or "").strip().split()).casefold()


def _register_reset_attempt(kind, value, window_seconds, max_attempts, cooldown_seconds):
    key = _reset_attempts_key(kind, value)
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=window_seconds)
        count = 1
    if count >= max_attempts:
        cache.set(_reset_cooldown_key(kind, value), True, timeout=cooldown_seconds)


def _is_reset_blocked(kind, value):
    return bool(cache.get(_reset_cooldown_key(kind, value)))


def is_password_reset_throttled(request, email):
    ip = client_ip(request)
    identifier = _normalize_reset_identifier(email)
    return _is_reset_blocked("ip", ip) or (bool(identifier) and _is_reset_blocked("id", identifier))


def register_password_reset_attempt(request, email):
    ip = client_ip(request)
    identifier = _normalize_reset_identifier(email)
    _register_reset_attempt("ip", ip, RESET_IP_WINDOW_SECONDS, RESET_IP_MAX_ATTEMPTS, RESET_IP_COOLDOWN_SECONDS)
    if identifier:
        _register_reset_attempt(
            "id",
            identifier,
            RESET_IDENTIFIER_WINDOW_SECONDS,
            RESET_IDENTIFIER_MAX_ATTEMPTS,
            RESET_IDENTIFIER_COOLDOWN_SECONDS,
        )
