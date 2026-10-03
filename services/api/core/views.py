from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def live(request):
    return JsonResponse({"status": "ok"})


@require_GET
def ready(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "unavailable", "checks": {"database": "down"}}, status=503)
    return JsonResponse({"status": "ok", "checks": {"database": "ok"}})


def csrf_failure(request, reason=""):
    return JsonResponse(
        {
            "code": "csrf_failed",
            "message": "Your session token is missing or out of date. Refresh the page and try again.",
            "fields": {},
            "request_id": getattr(request, "request_id", None),
        },
        status=403,
    )
