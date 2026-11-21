"""Browser push (REQ-019, EVAL-019; TASK-034): encryption, the devices a player adds, delivery as a
best-effort copy of the inbox, stale alerts never sent, and gone or refusing devices dropped."""

import json
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from django.test import override_settings
from django.utils import timezone

from notifications import push, service, webpush
from notifications.models import Notification, PushSubscription
from notifications.tasks import drop_expired_push_devices
from outbox import service as outbox
from outbox.models import Job

from .conftest import BrowserClient
from .helpers import logged_in, make_user

pytestmark = pytest.mark.django_db

PRIVATE, PUBLIC = webpush.new_keys()
ON = override_settings(WEB_PUSH_PRIVATE_KEY=PRIVATE, WEB_PUSH_SUBJECT="mailto:ops@example.com")

# A browser's own keys (from RFC 8291's example).
P256DH = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
AUTH = "BTBZMqHH6r4Tts7J_aSIgg"


def subscription(endpoint="https://fcm.googleapis.com/fcm/send/abc123", **extra):
    return {
        "endpoint": endpoint,
        "keys": {"p256dh": P256DH, "auth": AUTH},
        "label": "Chrome on Android",
        **extra,
    }


class Sent(list):
    def __init__(self):
        super().__init__()
        self.answers: list[int] = []


@pytest.fixture
def sent(monkeypatch):
    """Messages handed to the push service, and what it answers (201 unless told otherwise)."""
    calls = Sent()
    answers = calls.answers

    def fake_send(endpoint, p256dh, auth, payload, **options):
        calls.append({"endpoint": endpoint, "payload": payload, **options})
        return webpush.Result(answers.pop(0) if answers else 201)

    monkeypatch.setattr(webpush, "send", fake_send)
    return calls


def device_for(user, endpoint="https://fcm.googleapis.com/fcm/send/abc123", **extra):
    return PushSubscription.objects.create(user=user, endpoint=endpoint, p256dh=P256DH, auth=AUTH, **extra)


def test_encryption_matches_rfc_8291s_worked_example():
    sender = ec.derive_private_key(
        int.from_bytes(webpush.b64url_decode("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"),
        ec.SECP256R1(),
    )
    body = webpush.encrypt(
        b"When I grow up, I want to be a watermelon",
        P256DH,
        AUTH,
        sender_key=sender,
        salt=webpush.b64url_decode("DGv6ra1nlYgDCS1FRnbzlw"),
    )
    assert webpush.b64url_encode(body) == (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6"
        "PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
    )


def test_vapid_header_is_a_token_for_the_push_services_origin_signed_with_the_servers_key():
    header = webpush.vapid_authorization(
        "https://fcm.googleapis.com/fcm/send/abc", PRIVATE, "mailto:ops@example.com", now=1_000_000
    )
    token, key = header.removeprefix("vapid t=").split(", k=")
    assert key == PUBLIC == webpush.public_key_for(PRIVATE)
    head, claims, signature = token.split(".")
    assert json.loads(webpush.b64url_decode(claims)) == {
        "aud": "https://fcm.googleapis.com",
        "exp": 1_000_000 + 12 * 3600,
        "sub": "mailto:ops@example.com",
    }
    raw = webpush.b64url_decode(signature)
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), webpush.b64url_decode(PUBLIC))
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    public.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))  # raises if forged


def test_without_a_key_push_is_off_and_the_inbox_still_works(sent):
    amina = make_user("amina@example.com")
    client = logged_in(amina)
    status = client.get("/api/v1/me/push/").json()
    assert status == {"configured": False, "public_key": "", "devices": []}
    assert client.post("/api/v1/me/push/subscribe/", subscription(), format="json").status_code == 400
    device_for(amina)  # left over from when push was on
    service.notify([amina], "announcement", "Hello", subject="x:1")
    assert Notification.objects.filter(recipient=amina).count() == 1
    assert not Job.objects.filter(kind=push.SEND).exists() and sent == []


@ON
def test_a_player_adds_this_browser_and_sees_it_listed():
    client = logged_in(make_user("amina@example.com"))
    status = client.get("/api/v1/me/push/").json()
    assert status["configured"] is True and status["public_key"] == PUBLIC
    reply = client.post("/api/v1/me/push/subscribe/", subscription(expirationTime=None), format="json")
    assert reply.status_code == 200
    [device] = reply.json()["devices"]
    assert device["label"] == "Chrome on Android" and "endpoint" not in device and "p256dh" not in device
    # Subscribing again (new keys after the browser renewed them) updates the same device.
    again = client.post("/api/v1/me/push/subscribe/", subscription(), format="json").json()
    assert [d["id"] for d in again["devices"]] == [device["id"]]


@ON
@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/abc",  # not https
        "https://127.0.0.1/fcm/send/abc",
        "https://internal.example.com/push",
        "https://fcm.googleapis.com.evil.example/x",
        "https://fcm.googleapis.com:8443/fcm/send/abc",
    ],
)
def test_only_the_browsers_push_services_are_accepted_as_endpoints(endpoint):
    client = logged_in(make_user("amina@example.com"))
    reply = client.post("/api/v1/me/push/subscribe/", subscription(endpoint), format="json")
    assert reply.status_code == 400 and "endpoint" in reply.json()["fields"]
    assert not PushSubscription.objects.exists()


@ON
def test_apple_mozilla_and_windows_push_services_are_accepted():
    client = logged_in(make_user("amina@example.com"))
    for endpoint in (
        "https://web.push.apple.com/QGuQyavXutnMH",
        "https://api.push.apple.com/3/device/abc",
        "https://updates.push.services.mozilla.com/wpush/v2/gAAAA",
        "https://wns2-bl2p.notify.windows.com/w/?token=abc",
    ):
        assert (
            client.post("/api/v1/me/push/subscribe/", subscription(endpoint), format="json").status_code
            == 200
        )


@ON
def test_bad_browser_keys_are_refused():
    client = logged_in(make_user("amina@example.com"))
    bad = subscription()
    bad["keys"] = {"p256dh": "BAAAAAAA", "auth": AUTH}
    assert client.post("/api/v1/me/push/subscribe/", bad, format="json").status_code == 400
    bad["keys"] = {"p256dh": P256DH, "auth": "short"}
    assert client.post("/api/v1/me/push/subscribe/", bad, format="json").status_code == 400


@ON
def test_a_shared_browser_shows_only_the_player_signed_in_now():
    amina, baraka = make_user("amina@example.com"), make_user("baraka@example.com")
    logged_in(amina).post("/api/v1/me/push/subscribe/", subscription(), format="json")
    logged_in(baraka).post("/api/v1/me/push/subscribe/", subscription(), format="json")
    [device] = PushSubscription.objects.all()
    assert device.user == baraka


@ON
def test_a_player_removes_only_their_own_devices():
    amina, baraka = make_user("amina@example.com"), make_user("baraka@example.com")
    hers = device_for(amina)
    theirs = device_for(baraka, endpoint="https://fcm.googleapis.com/fcm/send/other")
    client = logged_in(amina)
    assert client.delete(f"/api/v1/me/push/devices/{theirs.id}/").status_code == 404
    client.post("/api/v1/me/push/unsubscribe/", {"endpoint": theirs.endpoint}, format="json")
    assert PushSubscription.objects.filter(pk=theirs.pk).exists()
    assert client.post("/api/v1/me/push/unsubscribe/", {"endpoint": hers.endpoint}, format="json").json() == {
        "configured": True,
        "public_key": PUBLIC,
        "devices": [],
    }


def test_signed_out_callers_cant_see_or_add_devices():
    anonymous = BrowserClient()
    assert anonymous.get("/api/v1/me/push/").status_code == 401
    assert anonymous.post("/api/v1/me/push/subscribe/", subscription(), format="json").status_code == 401


@ON
def test_an_alert_goes_once_to_each_of_the_players_devices(sent):
    amina = make_user("amina@example.com")
    phone = device_for(amina)
    laptop = device_for(amina, endpoint="https://updates.push.services.mozilla.com/wpush/v2/laptop")
    device_for(make_user("baraka@example.com"), endpoint="https://fcm.googleapis.com/fcm/send/other")
    for _ in range(3):  # the same event, sent again, is one alert and one message per device
        service.notify(
            [amina], "table_call", "Table 3 now", subject="match:1", version="r1", link="/matches/1"
        )
    outbox.work()
    assert sorted(c["endpoint"] for c in sent) == sorted([phone.endpoint, laptop.endpoint])
    payload = sent[0]["payload"]
    assert payload["title"] == "Table 3 now" and payload["link"] == "/matches/1"
    assert payload["tag"] == "match:1" and payload["urgent"] is True
    assert sent[0]["ttl"] == 600 and len(sent[0]["topic"]) <= 32
    phone.refresh_from_db()
    assert phone.last_sent_at is not None
    outbox.work()
    assert len(sent) == 2


@ON
def test_an_alert_superseded_or_read_before_it_goes_out_is_never_pushed(sent):
    amina = make_user("amina@example.com")
    device_for(amina)
    service.notify([amina], "table_call", "Table 3 now", subject="match:1", version="r1")
    service.notify([amina], "table_call", "Table 5 now", subject="match:1", version="r2")
    service.notify([amina], "announcement", "Read already", subject="x:9")
    Notification.objects.filter(title="Read already").update(read_at=timezone.now())
    outbox.work()
    assert [c["payload"]["title"] for c in sent] == ["Table 5 now"]


@ON
def test_a_category_switched_off_sends_no_push(sent):
    amina = make_user("amina@example.com")
    device_for(amina)
    logged_in(amina).put(
        "/api/v1/me/notification-preferences/",
        {"preferences": [{"category": "soda", "enabled": False}]},
        format="json",
    )
    service.notify([amina], "soda", "A challenge", subject="soda:1")
    outbox.work()
    assert sent == []


@ON
def test_a_device_the_push_service_says_is_gone_is_dropped(sent):
    amina = make_user("amina@example.com")
    device = device_for(amina)
    sent.answers.append(410)
    service.notify([amina], "announcement", "Hello", subject="x:1")
    outbox.work()
    assert not PushSubscription.objects.filter(pk=device.pk).exists()
    assert Notification.objects.filter(recipient=amina).count() == 1  # the inbox keeps it


@ON
def test_a_busy_push_service_is_tried_again_later(sent):
    amina = make_user("amina@example.com")
    device_for(amina)
    sent.answers.extend([503, 201])
    service.notify([amina], "announcement", "Hello", subject="x:1")
    outbox.work()
    job = Job.objects.get(kind=push.SEND)
    assert job.status == Job.Status.PENDING and job.attempts == 1
    Job.objects.filter(pk=job.pk).update(available_at=timezone.now())
    outbox.work()
    job.refresh_from_db()
    assert job.status == Job.Status.DONE and len(sent) == 2


@ON
def test_a_device_that_keeps_refusing_is_dropped_after_three_tries(sent):
    amina = make_user("amina@example.com")
    device = device_for(amina)
    sent.answers.extend([403, 403, 403])
    for n in range(3):
        service.notify([amina], "announcement", f"Hello {n}", subject=f"x:{n}")
        outbox.work()
        assert PushSubscription.objects.filter(pk=device.pk).exists() == (n < 2)
    assert Job.objects.filter(kind=push.SEND, status=Job.Status.DONE).count() == 3


@ON
def test_a_device_that_changed_hands_doesnt_get_the_last_players_alerts(sent):
    amina, baraka = make_user("amina@example.com"), make_user("baraka@example.com")
    device = device_for(amina)
    service.notify([amina], "announcement", "For Amina", subject="x:1")
    device.user = baraka
    device.save()
    outbox.work()
    assert sent == []


@ON
def test_expired_subscriptions_are_dropped(sent):
    amina = make_user("amina@example.com")
    expired = device_for(amina, expires_at=timezone.now() - timedelta(minutes=1))
    kept = device_for(amina, endpoint="https://fcm.googleapis.com/fcm/send/kept")
    service.notify([amina], "announcement", "Hello", subject="x:1")
    outbox.work()
    assert [c["endpoint"] for c in sent] == [kept.endpoint]
    assert not PushSubscription.objects.filter(pk=expired.pk).exists()
    later = device_for(amina, endpoint="https://fcm.googleapis.com/fcm/send/later")
    PushSubscription.objects.filter(pk=later.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert drop_expired_push_devices() == 1
    assert list(PushSubscription.objects.all()) == [kept]


def test_the_message_sent_is_encrypted_for_the_browser_and_signed(monkeypatch):
    seen = {}

    class Reply:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["headers"] = dict(request.header_items())
        seen["body"] = request.data
        return Reply()

    monkeypatch.setattr(webpush.urllib.request, "urlopen", fake_urlopen)
    result = webpush.send(
        "https://fcm.googleapis.com/fcm/send/abc",
        P256DH,
        AUTH,
        {"title": "Private text"},
        private_key_b64=PRIVATE,
        subject="mailto:ops@example.com",
        ttl=600,
        topic="abc",
    )
    assert result.delivered
    assert seen["headers"]["Content-encoding"] == "aes128gcm" and seen["headers"]["Ttl"] == "600"
    assert seen["headers"]["Authorization"].startswith("vapid t=")
    assert b"Private text" not in seen["body"]
