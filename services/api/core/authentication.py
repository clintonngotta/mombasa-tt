from rest_framework.authentication import SessionAuthentication as DrfSessionAuthentication


class SessionAuthentication(DrfSessionAuthentication):
    """Answer 401 (not 403) when no session exists, so clients can tell 'log in' from 'not allowed'."""

    def authenticate_header(self, request):
        return "Session"
