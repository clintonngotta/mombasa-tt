from django.core.cache import caches
from redis.exceptions import RedisError
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle

from core.cache import warn_unavailable

# Allowances that guard passwords, codes and messages sent to other people. While the shared count is
# out of reach these refuse every request: a count kept per process would let a guesser multiply the
# allowance by the number of processes. The others fall back to this process's own count instead, so
# the site keeps working for players while Redis is down (entries and uploads included: they are
# checked again by the API's own capacity and size rules, which don't depend on Redis).
CLOSED_WHEN_UNCOUNTED = frozenset({"auth_login", "auth_email", "invitations"})


class SharedCount:
    """Counts requests in the shared cache (Redis in production), so every API process sees the same
    count. Each allowance period is a window with one counter that Redis adds to in a single step, so
    requests arriving together on different processes can't overwrite each other's count (DRF's own
    throttles read a list and write it back). At a window's edge a client can get up to twice the
    allowance in one period; never more.

    If Redis can't be reached, the allowances in CLOSED_WHEN_UNCOUNTED refuse the request and the rest
    count in this process's memory until Redis answers again."""

    # Set when this request was refused only because the shared count couldn't be reached.
    uncounted = False

    def ready(self, request, view) -> bool:
        return self.rate is not None

    def allow_request(self, request, view):
        self.uncounted = False
        if not self.ready(request, view):
            return True
        key = self.get_cache_key(request, view)
        if key is None:
            return True
        try:
            return self.count(caches["default"], key)
        except RedisError:
            warn_unavailable(f"rate limit {self.scope}")
        if self.scope in CLOSED_WHEN_UNCOUNTED:
            self.uncounted = True
            return False
        return self.count(caches["local"], key)

    def count(self, store, key) -> bool:
        window = int(self.timer() // self.duration)
        self.window_ends = (window + 1) * self.duration
        key = f"{key}_{window}"
        store.add(key, 0, self.duration + 1)
        try:
            seen = store.incr(key)
        except ValueError:  # the window's counter expired between the two calls
            store.set(key, 1, self.duration + 1)
            seen = 1
        return seen <= self.num_requests

    def wait(self):
        if self.uncounted:
            return float(self.duration)
        return max(self.window_ends - self.timer(), 1.0)


class ScopedThrottle(SharedCount, ScopedRateThrottle):
    """DRF's scoped throttle (views that set `throttle_scope`), counted across processes."""

    def ready(self, request, view) -> bool:
        self.scope = getattr(view, self.scope_attr, None)
        if not self.scope:
            return False
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return True


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
