"""Changes sent twice with the same Idempotency-Key are made once (REQ-013, REQ-035). The app keeps
changes made offline and sends them again when it can't tell whether a reply was lost."""

from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import IdempotentRequest
from matchlog.models import PersonalMatch

from .conftest import BrowserClient
from .helpers import logged_in, make_user
from .test_matchlog import payload

pytestmark = pytest.mark.django_db
URL = "/api/v1/me/matches/"
KEY = "retry-" + "x" * 20  # a made-up key; any 16-64 letters, digits and dashes


def test_a_repeat_returns_the_first_answer_and_changes_nothing():
    ama = logged_in(make_user("ama@example.com"))
    first = ama.post(URL, payload(), format="json", HTTP_IDEMPOTENCY_KEY=KEY)
    assert first.status_code == 201
    again = ama.post(URL, payload(), format="json", HTTP_IDEMPOTENCY_KEY=KEY)
    assert again.status_code == 201 and again.json() == first.json()
    assert again["Idempotent-Replayed"] == "true"
    assert PersonalMatch.objects.count() == 1
    # Without a key every request counts.
    ama.post(URL, payload(), format="json")
    assert PersonalMatch.objects.count() == 2


def test_refusals_are_kept_too_and_keys_belong_to_one_account():
    ama = logged_in(make_user("ama@example.com"))
    refused = ama.post(URL, payload(label=" "), format="json", HTTP_IDEMPOTENCY_KEY=KEY)
    assert refused.status_code == 400
    # The same key replays the refusal even if the body is now fine: a retry is the same change.
    assert ama.post(URL, payload(), format="json", HTTP_IDEMPOTENCY_KEY=KEY).status_code == 400
    # Another account using the same key makes its own change.
    ben = logged_in(make_user("ben@example.com"))
    assert ben.post(URL, payload(), format="json", HTTP_IDEMPOTENCY_KEY=KEY).status_code == 201
    assert PersonalMatch.objects.count() == 1


def test_bad_reused_and_unfinished_keys():
    user = make_user("ama@example.com")
    ama = logged_in(user)
    bad = ama.post(URL, payload(), format="json", HTTP_IDEMPOTENCY_KEY="short")
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_idempotency_key"
    ama.post(URL, payload(), format="json", HTTP_IDEMPOTENCY_KEY=KEY)
    other = ama.post("/api/v1/me/matches/x/", {}, format="json", HTTP_IDEMPOTENCY_KEY=KEY)
    assert other.status_code == 422 and other.json()["code"] == "idempotency_key_reused"
    # A first request still running: the repeat is told to wait.
    IdempotentRequest.objects.create(user=user, key="a" * 20, method="POST", path=URL)
    busy = ama.post(URL, payload(), format="json", HTTP_IDEMPOTENCY_KEY="a" * 20)
    assert busy.status_code == 409 and busy.json()["code"] == "request_in_progress"
    # One that never finished (the server restarted) is given up after a while, and the change is made.
    IdempotentRequest.objects.filter(key="a" * 20).update(created_at=timezone.now() - timedelta(minutes=6))
    assert ama.post(URL, payload(), format="json", HTTP_IDEMPOTENCY_KEY="a" * 20).status_code == 201
    # Signed out, the header changes nothing: the request is refused as before.
    signed_out = BrowserClient().post(URL, payload(), format="json", HTTP_IDEMPOTENCY_KEY=KEY)
    assert signed_out.status_code in (401, 403)


def test_old_keys_are_forgotten(settings):
    from core.tasks import forget_idempotency_keys

    user = make_user("ama@example.com")
    old = IdempotentRequest.objects.create(user=user, key="b" * 20, method="POST", path=URL, status=201)
    IdempotentRequest.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=settings.IDEMPOTENCY_KEEP_DAYS + 1)
    )
    IdempotentRequest.objects.create(user=user, key="c" * 20, method="POST", path=URL, status=201)
    assert forget_idempotency_keys() == 1
    assert list(IdempotentRequest.objects.values_list("key", flat=True)) == ["c" * 20]
