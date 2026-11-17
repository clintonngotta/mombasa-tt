from io import BytesIO

from django.utils import timezone
from PIL import Image

from accounts.models import User

from .conftest import PASSWORD, BrowserClient


def make_user(email, **extra):
    extra.setdefault("display_name", email.split("@")[0])
    return User.objects.create_user(email=email, password=PASSWORD, email_verified_at=timezone.now(), **extra)


def logged_in(user):
    client = BrowserClient()
    response = client.post("/api/v1/auth/login/", {"email": user.email, "password": PASSWORD}, format="json")
    assert response.status_code == 200
    return client


def image_upload(fmt="JPEG", size=(900, 600), name="me.jpg", **save) -> BytesIO:
    """An in-memory image file ready to post as a multipart upload."""
    out = BytesIO()
    Image.new("RGB", size, "navy").save(out, fmt, **save)
    out.seek(0)
    out.name = name
    return out
