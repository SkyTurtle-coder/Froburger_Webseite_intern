class ContentSecurityPolicyReportOnlyMiddleware:
    """SEC-017: Report-Only CSP rollout for the Django portal.

    This only makes the browser LOG would-be violations to its console
    (and to a report endpoint, if one is ever configured below) - it never
    blocks anything. The plan is: deploy this, watch for violations across
    real usage for a while, tighten the policy to remove anything that
    turns out to be unnecessarily permissive, and only then consider
    dropping "-Report-Only" to actually enforce it. Do not skip the
    observation period - the Django portal has less third-party surface
    than the WordPress site (no Elementor, no external embeds; this is a
    stricter starting point than what's shipped for WordPress via .htaccess),
    but a Report-Only period is still the safe way to confirm that.
    """

    POLICY = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'self'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Content-Security-Policy-Report-Only"] = self.POLICY
        return response
