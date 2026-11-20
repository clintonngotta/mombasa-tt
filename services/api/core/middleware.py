import logging
import re
import time
import uuid

from django.conf import settings
from django.http import JsonResponse

from .logging import request_id_var

_VALID_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
logger = logging.getLogger("request")


class RequestIdMiddleware:
    """Tags each request with an ID (reusing a sane proxy-supplied X-Request-ID) for errors and logs, and
    logs one line per request: method, route, status and duration. The query string is left out."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get("X-Request-ID", "")
        request.request_id = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request.request_id)
        started = time.monotonic()
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = request.request_id
            if not request.path.startswith("/health/"):
                logger.info(
                    "%s %s %s",
                    request.method,
                    request.path,
                    response.status_code,
                    extra={
                        "method": request.method,
                        "path": request.path,
                        "status": response.status_code,
                        "duration_ms": round((time.monotonic() - started) * 1000, 1),
                    },
                )
            return response
        finally:
            request_id_var.reset(token)


class ClientBuildMiddleware:
    """Turns away a web app build older than MIN_CLIENT_BUILD (REQ-035) with 426 and code
    "client_outdated", so a cached old version asks to update instead of failing in odd ways. A request
    without the X-Client-Build header (scripts, the admin, a native client yet to come) is let through,
    as is everything when MIN_CLIENT_BUILD is unset. Nothing is changed by a refused request: the app keeps
    its queued scores and sends them once updated."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        oldest = settings.MIN_CLIENT_BUILD
        build = request.headers.get("X-Client-Build", "")
        if oldest and request.path.startswith("/api/") and build.isdigit() and int(build) < oldest:
            return JsonResponse(
                {
                    "code": "client_outdated",
                    "message": "This version of Coast TT is out of date. Update the app to carry on: "
                    "anything waiting to be sent stays on your device.",
                    "fields": {},
                    "request_id": getattr(request, "request_id", None),
                },
                status=426,
            )
        return self.get_response(request)
