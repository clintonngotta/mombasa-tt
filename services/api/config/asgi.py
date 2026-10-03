import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
# Channels routing is added with live updates (TASK-007).
application = get_asgi_application()
