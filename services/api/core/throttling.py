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


class LiveReadThrottle(PublicReadThrottle):
    """Signed-out reads of the live score list (TASK-084). A venue's spectators often share one address
    (the hall's Wi-Fi) and their pages fetch the list again after every point, so it has a limit of its
    own, still counted per client address."""

    scope = "live_reads"
