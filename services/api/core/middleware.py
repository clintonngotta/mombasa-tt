import json
import logging
import re
import time
import uuid
from datetime import timedelta

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone

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


_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9-]{16,64}$")
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
_ABANDONED_AFTER = timedelta(minutes=5)


def _error(request, status, code, message):
    return JsonResponse(
        {"code": code, "message": message, "fields": {}, "request_id": getattr(request, "request_id", None)},
        status=status,
    )


class IdempotencyMiddleware:
    """Makes a change safe to send twice (REQ-013, REQ-035). The app keeps changes made offline and sends
    them when it is back online. A lost reply means it can't tell whether a change got through, so it
    sends it again with the same Idempotency-Key header.

    The first request with a key is handled as usual and its answer is kept. A repeat gets the kept
    answer, marked Idempotent-Replayed, and changes nothing. A repeat that arrives while the first is
    still running gets 409 request_in_progress, and the app tries again later. Reusing a key for a
    different change gets 422 idempotency_key_reused. Server errors (5xx), 401, 403 and 429 are not kept,
    so a retry runs again; a first request that never finished is given up after five minutes. Keys
    belong to an account, only apply to signed-in API changes, and are forgotten after
    IDEMPOTENCY_KEEP_DAYS (core.tasks.forget_idempotency_keys)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        key = request.headers.get("Idempotency-Key", "")
        user = getattr(request, "user", None)
        if (
            not key
            or request.method in _SAFE_METHODS
            or not request.path.startswith("/api/")
            or not (user and user.is_authenticated)
        ):
            return self.get_response(request)
        if not _IDEMPOTENCY_KEY.match(key):
            return _error(request, 400, "invalid_idempotency_key", "The Idempotency-Key header isn't valid.")

        from django.db import IntegrityError, transaction

        from .models import IdempotentRequest

        try:
            with transaction.atomic():
                record = IdempotentRequest.objects.create(
                    user=user, key=key, method=request.method, path=request.path[:500]
                )
        except IntegrityError:
            kept = IdempotentRequest.objects.filter(user=user, key=key).first()
            if kept is None:  # forgotten between the two queries: let the client try again
                return _error(request, 409, "request_in_progress", "This change is still being saved.")
            if kept.method != request.method or kept.path != request.path[:500]:
                return _error(
                    request,
                    422,
                    "idempotency_key_reused",
                    "This Idempotency-Key was already used for a different change.",
                )
            if kept.status is None:
                # A first request that died half way (a restarted server) mustn't block the change forever.
                if kept.created_at > timezone.now() - _ABANDONED_AFTER:
                    return _error(request, 409, "request_in_progress", "This change is still being saved.")
                kept.delete()
                return self(request)
            replay = (
                JsonResponse(kept.body, status=kept.status, safe=False)
                if kept.body is not None
                else HttpResponse(status=kept.status)
            )
            replay["Idempotent-Replayed"] = "true"
            return replay

        response = self.get_response(request)
        body = None
        # Server errors, and refusals that changed nothing and may pass later (signed out, CSRF, throttled),
        # are not kept: a retry runs again.
        keep = response.status_code < 500 and response.status_code not in (401, 403, 429)
        if keep and response.status_code != 204:
            if "application/json" in response.get("Content-Type", "") and not response.streaming:
                try:
                    body = json.loads(response.content or b"null")
                except ValueError:
                    keep = False
            else:
                keep = False
        if keep:
            record.status = response.status_code
            record.body = body
            record.save(update_fields=["status", "body"])
        else:
            record.delete()
        return response
