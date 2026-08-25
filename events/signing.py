"""Request authentication for the WordPress -> Django public event-signup API.

WordPress signs each signup POST with a shared secret; Django verifies the
signature, checks the timestamp is within a small window, and guards against
replay by caching the signature for the duration of that window.

A missing secret is never treated as "no authentication required" - see
SEC-002 in the security audit.
"""
import hashlib
import hmac
import time

TIMESTAMP_HEADER = "X-AVF-Timestamp"
SIGNATURE_HEADER = "X-AVF-Signature"
DEFAULT_TOLERANCE_SECONDS = 300


def _body_hash(body_bytes):
    return hashlib.sha256(body_bytes or b"").hexdigest()


def canonical_string(slug, timestamp, body_bytes):
    return "\n".join(["POST", str(slug), str(timestamp), _body_hash(body_bytes)])


def compute_signature(secret, slug, timestamp, body_bytes):
    message = canonical_string(slug, timestamp, body_bytes).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_signed_request(secret, slug, timestamp, body_bytes, signature, *, tolerance_seconds=DEFAULT_TOLERANCE_SECONDS, now=None):
    """Returns True only for a signature that matches and a timestamp inside the tolerance window."""
    if not (secret and timestamp and signature):
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    current = int(now if now is not None else time.time())
    if abs(current - ts) > tolerance_seconds:
        return False
    expected = compute_signature(secret, slug, ts, body_bytes)
    return hmac.compare_digest(expected, signature)
