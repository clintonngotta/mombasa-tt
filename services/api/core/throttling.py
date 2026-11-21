from rest_framework.throttling import SimpleRateThrottle


class PublicReadThrottle(SimpleRateThrottle):
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
