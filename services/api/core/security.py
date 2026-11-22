"""Which browser origins may talk to the API, and the rate limit on Django admin's login form.

The PWA and the API share one origin behind the proxy (deployment.md), so the API sends no CORS headers
and browsers keep other sites from reading its answers. The allowed origins are that origin plus the
exact ones in DJANGO_CSRF_TRUSTED_ORIGINS. They gate three things:

- state-changing API requests (OriginCheckMiddleware), including the signed-out ones such as log in and
  sign up, so a page on another site can't post to the API with or without the visitor's cookies;
- CSRF checks (Django's own CsrfViewMiddleware reads the same setting);
- WebSockets (websocket_origins, used by config/asgi.py)."""

from django.conf import settings
from django.http import JsonResponse
from rest_framework.throttling import SimpleRateThrottle

from core.throttling import SharedCount

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def origin_allowed(origin: str, request) -> bool:
    """The request's own origin (scheme and host as the proxy forwards them) or a configured one.
    "null" (sandboxed frames, some redirects) is never allowed."""
    if origin == f"{request.scheme}://{request.get_host()}":
        return True
    return origin in settings.CSRF_TRUSTED_ORIGINS


class OriginCheckMiddleware:
    """Refuse a state-changing /api/ request whose Origin header names a site that isn't allowed.
    Browsers send Origin with every cross-site POST, PUT, PATCH and DELETE; native clients and tests that
    send none are left to the session and CSRF checks."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        origin = request.headers.get("Origin")
        if (
            origin is not None
            and request.method not in _SAFE_METHODS
            and request.path.startswith("/api/")
            and not origin_allowed(origin, request)
        ):
            return JsonResponse(
                {
                    "code": "origin_not_allowed",
                    "message": "This request came from a site that isn't allowed to use Coast TT.",
                    "fields": {},
                    "request_id": getattr(request, "request_id", None),
                },
                status=403,
            )
        return self.get_response(request)


class _AdminLoginThrottle(SharedCount, SimpleRateThrottle):
    """The API's login allowance (THROTTLE_AUTH_LOGIN), per client address, for admin's login form,
    shared across processes and closed while the shared count is out of reach."""

    scope = "auth_login"
    cache_format = "throttle_admin_login_%(ident)s"

    def get_cache_key(self, request, view):
        return self.cache_format % {"ident": self.get_ident(request)}


class AdminLoginThrottleMiddleware:
    """Django admin's login form has no rate limit of its own, so password guessing there is held to the
    same allowance as the API's log in."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and request.path.startswith("/admin/login/"):
            if not _AdminLoginThrottle().allow_request(request, None):
                return JsonResponse(
                    {
                        "code": "throttled",
                        "message": "Too many attempts. Try again in a minute.",
                        "fields": {},
                    },
                    status=429,
                )
        return self.get_response(request)


def websocket_origins() -> list[str]:
    """Origins a WebSocket may be opened from: the exact trusted origins, and while developing also any
    port of the allowed hosts (Vite and the compose stack serve the app on several)."""
    origins = list(settings.CSRF_TRUSTED_ORIGINS)
    if settings.DEBUG:
        origins += settings.ALLOWED_HOSTS or ["localhost", "127.0.0.1", "[::1]"]
    return origins
