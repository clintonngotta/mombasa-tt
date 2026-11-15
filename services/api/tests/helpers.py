from django.utils import timezone

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
