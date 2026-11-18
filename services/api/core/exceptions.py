from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.views import exception_handler as drf_exception_handler


class ApiException(exceptions.APIException):
    """Domain error with a stable machine-readable code."""

    def __init__(self, code: str, message: str, status_code: int = status.HTTP_400_BAD_REQUEST, extra=None):
        super().__init__(detail=message, code=code)
        self.status_code = status_code
        self.extra = extra or {}  # further keys of the error body, such as a list of conflicts


def _flatten(detail) -> str:
    if isinstance(detail, list):
        return _flatten(detail[0]) if detail else ""
    if isinstance(detail, dict):
        return _flatten(next(iter(detail.values()), ""))
    return str(detail)


def api_exception_handler(exc, context):
    """Shape every API error as {code, message, fields, request_id} (spec REQ-032)."""
    # DRF maps Django's Http404/PermissionDenied internally; map them here too so they keep their codes.
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied()
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    request = context["request"]
    fields: dict[str, str] = {}
    if isinstance(exc, exceptions.ValidationError) and isinstance(exc.detail, dict):
        fields = {name: _flatten(value) for name, value in exc.detail.items() if name != "non_field_errors"}
        non_field = exc.detail.get("non_field_errors")
        code = "validation_error"
        message = _flatten(non_field) if non_field else "Some fields need attention."
    else:
        codes = exc.get_codes() if isinstance(exc, exceptions.APIException) else "error"
        code = codes if isinstance(codes, str) else "error"
        message = _flatten(exc.detail) if isinstance(exc, exceptions.APIException) else "Request failed."

    response.data = {
        "code": code,
        "message": message,
        "fields": fields,
        "request_id": getattr(request, "request_id", None),
        **getattr(exc, "extra", {}),
    }
    return response
