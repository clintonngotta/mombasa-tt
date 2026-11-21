import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django_asgi_app = get_asgi_application()  # set up Django before importing anything that uses models

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import OriginValidator  # noqa: E402

from core.security import websocket_origins  # noqa: E402
from realtime.routing import websocket_urlpatterns  # noqa: E402

# HTTP goes to Django as before. A WebSocket must come from an allowed origin (core/security.py), so
# another site can't open one with the visitor's cookie; the consumer decides what the session may watch.
application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": OriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns)), websocket_origins()
        ),
    }
)
