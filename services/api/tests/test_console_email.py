from io import StringIO
from urllib.parse import urlencode

import pytest
from django.core.mail import get_connection

from accounts.emails import send_password_reset_email, send_verification_email
from accounts.models import User


@pytest.mark.parametrize("kind", ["verification", "reset"])
def test_console_email_prints_copyable_links(kind, settings, monkeypatch):
    stream = StringIO()
    connection = get_connection("core.email.EmailBackend", stream=stream)
    monkeypatch.setattr("django.core.mail.get_connection", lambda **kwargs: connection)
    user = User(email="test@example.com", display_name="Test")
    token = "eyJ" + "x" * 180 + ":timestamp:signature"
    if kind == "verification":
        monkeypatch.setattr("accounts.emails.make_verification_token", lambda user: token)
        path, params = "/verify-email", {"token": token}
        send_verification_email(user)
    else:
        monkeypatch.setattr("accounts.emails.make_reset_params", lambda user: ("user-id", token))
        path, params = "/reset-password", {"uid": "user-id", "token": token}
        send_password_reset_email(user)

    link = f"{settings.FRONTEND_URL}{path}?{urlencode(params)}"
    assert link in stream.getvalue().splitlines()
