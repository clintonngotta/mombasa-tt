from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def live(request):
    return JsonResponse({"status": "ok"})


@require_GET
def ready(request):
    """Ready when the database answers, and Redis too where it is configured."""
    checks = {"database": "ok"}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        checks["database"] = "down"
    if settings.REDIS_URL:
        checks["redis"] = "ok" if _redis_answers() else "down"
    if "down" in checks.values():
        return JsonResponse({"status": "unavailable", "checks": checks}, status=503)
    return JsonResponse({"status": "ok", "checks": checks})


def _redis_answers() -> bool:
    import redis

    try:
        client = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=1, socket_connect_timeout=1)
        return bool(client.ping())
    except redis.RedisError:
        return False


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
