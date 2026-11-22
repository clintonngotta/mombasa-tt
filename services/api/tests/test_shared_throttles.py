"""Rate limits are counted in the shared cache (Redis in production), and what happens when it is down:
the login, email and invitation allowances refuse, the others count in the process, and the live score
list and scoring carry on without its one-second copy."""

import pytest
from django.core.cache import caches
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from core import throttling
from scoring import live

from .conftest import PASSWORD, BrowserClient
from .helpers import make_user
from .test_live_scores import live_url, umpire_deck
from .test_umpire_scoring import START, final, point  # noqa: F401

pytestmark = pytest.mark.django_db


class RedisDown:
    """A cache whose every call fails the way the Redis backend does when Redis can't be reached."""

    def _down(self, *args, **kwargs):
        raise RedisConnectionError("Redis is down")

    get = set = delete = add = _down


@pytest.fixture
def counts_down(monkeypatch):
    monkeypatch.setattr(throttling, "caches", {"default": RedisDown(), "local": caches["local"]})


@pytest.fixture
def rates(monkeypatch):
    def use(**changed):
        changed = {**SimpleRateThrottle.THROTTLE_RATES, **changed}
        monkeypatch.setattr(SimpleRateThrottle, "THROTTLE_RATES", changed)

    return use


def test_the_api_counts_rate_limits_in_the_shared_cache(rates):
    rates(auth_login="2/min")
    client = BrowserClient()
    for _ in range(2):
        client.post("/api/v1/auth/login/", {"email": "a@example.com", "password": "x" * 12}, format="json")
    assert any(":throttle_auth_login_" in key for key in caches["default"]._cache)
    assert not caches["local"]._cache


def test_logging_in_is_refused_while_the_count_is_out_of_reach(counts_down):
    user = make_user("ama@example.com")
    response = BrowserClient().post(
        "/api/v1/auth/login/", {"email": user.email, "password": PASSWORD}, format="json"
    )
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_sending_a_sign_in_email_is_refused_while_the_count_is_out_of_reach(counts_down):
    response = BrowserClient().post(
        "/api/v1/auth/password-reset/", {"email": "ama@example.com"}, format="json"
    )
    assert response.status_code == 429


def test_admin_login_is_refused_while_the_count_is_out_of_reach(client, counts_down):
    answer = client.post("/admin/login/", {"username": "root@example.com", "password": "guess"})
    assert answer.status_code == 429


def test_public_pages_count_in_the_process_while_the_count_is_out_of_reach(staff, club, final, rates):  # noqa: F811
    rates(live_reads="2/min")
    visitor = APIClient()
    # Redis goes down only after the fixtures have logged their people in.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(throttling, "caches", {"default": RedisDown(), "local": caches["local"]})
        answers = [visitor.get(live_url(final["cup"])).status_code for _ in range(3)]
    assert answers == [200, 200, 429]
    assert any("throttle_live_reads_" in key for key in caches["local"]._cache)


def test_scores_are_saved_and_shown_while_the_live_copy_is_out_of_reach(staff, club, final, monkeypatch):  # noqa: F811
    deck = umpire_deck(staff, club, final)
    monkeypatch.setattr(live, "cache", RedisDown())
    deck.send(START, point("a"))
    shown = APIClient().get(live_url(final["cup"]))
    assert shown.status_code == 200
    assert shown.json()[0]["score"]["points"] == [1, 0]
