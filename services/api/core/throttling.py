import logging

from django.core.cache import caches
from redis.exceptions import RedisError
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle

logger = logging.getLogger(__name__)

# Allowances that guard passwords, codes and messages sent to other people. While the shared count is
# out of reach these refuse every request: a count kept per process would let a guesser multiply the
# allowance by the number of processes. The others fall back to this process's own count instead, so
# the site keeps working for players while Redis is down.
CLOSED_WHEN_UNCOUNTED = frozenset({"auth_login", "auth_email", "invitations"})


class SharedCount:
    """Counts requests in the shared cache (Redis in production), so every API process sees the same
    count. If Redis can't be reached, the allowances in CLOSED_WHEN_UNCOUNTED refuse the request and
    the rest count in this process's memory until Redis answers again."""

    def allow_request(self, request, view):
        self.cache = caches["default"]
        try:
            return super().allow_request(request, view)
        except RedisError:
            logger.warning("rate limit count unavailable", extra={"scope": self.scope})
        if self.scope in CLOSED_WHEN_UNCOUNTED:
            self.history = []
            self.uncounted = True
            return False
        self.cache = caches["local"]
        return super().allow_request(request, view)

    def wait(self):
        if getattr(self, "uncounted", False):
            return float(self.duration)
        return super().wait()


class ScopedThrottle(SharedCount, ScopedRateThrottle):
    """DRF's scoped throttle (views that set `throttle_scope`), counted across processes."""


class PublicReadThrottle(SharedCount, SimpleRateThrottle):
    """Signed-out reads of public pages (TASK-035), counted per client address, so a scraper can't
    load the database through the pages anyone may open. Signed-in players and every other view are
    left to the scoped throttles."""

    scope = "public_reads"

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            return None
        if not getattr(view, "public_actions", None):
            return None
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LiveReadThrottle(PublicReadThrottle):
    """Signed-out reads of the live score list (TASK-084). A venue's spectators often share one address
    (the hall's Wi-Fi) and their pages fetch the list again after points (at most once a second each),
    so it has a limit of its own, still counted per client address. The list itself is cached for a
    second, so the database sees one read a second per tournament however many people watch."""

    scope = "live_reads"
