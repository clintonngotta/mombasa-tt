import logging
import re
import time
import uuid

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
