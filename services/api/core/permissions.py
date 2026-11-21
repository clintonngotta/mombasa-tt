from rest_framework.permissions import SAFE_METHODS, BasePermission


def is_platform_super_admin(user):
    """The platform grant is explicit and valid only for active, signed-in superusers."""
    return bool(user.is_authenticated and user.is_active and user.is_superuser)


class PublicReads(BasePermission):
    """Published competition pages are public (REQ-020, TASK-035): a signed-out caller may use the view's
    reads named in `public_actions` (a viewset) or any GET of a view with `public_actions = ("get",)`.
    Everything else still needs a session, so a signed-out caller gets 401 as before."""

    def has_permission(self, request, view):
        if request.user and request.user.is_authenticated:
            return True
        if request.method not in SAFE_METHODS:
            return False
        action = getattr(view, "action", None) or request.method.lower()
        return action in getattr(view, "public_actions", ())
