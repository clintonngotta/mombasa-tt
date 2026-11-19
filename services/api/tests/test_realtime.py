"""TASK-007: live updates over WebSockets, the Celery outbox wake-up, structured logs and readiness."""

import json
import logging

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from channels.testing import WebsocketCommunicator

from competitions.models import Tournament
from config.asgi import application
from core.logging import JsonFormatter, RequestIdFilter, request_id_var
from outbox import service as outbox
from outbox.models import Job
from realtime import broadcast

from .helpers import logged_in, make_user
from .test_official_results import enter, knockout
from .test_tournaments import add_event, do, make_tournament
from .test_venues import add_table, make_venue

pytestmark = pytest.mark.django_db

ORIGIN = (b"origin", b"http://localhost")


@pytest.fixture
def hall(staff, club):
    venue = make_venue(staff, club)
    for label in ("Table 1", "Table 2"):
        add_table(staff, club, venue, label)
    return venue


def path(tournament_id) -> str:
    return f"/api/v1/ws/tournaments/{tournament_id}/"


def cookies(client) -> tuple[bytes, bytes]:
    return (b"cookie", f"sessionid={client.cookies['sessionid'].value}".encode())


def opens(tournament_id, headers) -> tuple[bool, int | None]:
    """Whether a WebSocket to the tournament is accepted, and the close code if it is not."""

    async def attempt():
        socket = WebsocketCommunicator(application, path(tournament_id), headers=headers)
        connected, code = await socket.connect()
        await socket.disconnect()
        return connected, code

    return async_to_sync(attempt)()


# The consumer reads the database from its own thread, so these tests commit.
@pytest.mark.django_db(transaction=True)
def test_a_signed_in_viewer_hears_that_a_tournament_changed_but_not_what(
    staff, club, hall, django_capture_on_commit_callbacks
):
    tournament = add_event(staff, make_tournament(staff, club, hall), name="Singles")
    do(staff, tournament, "publish")
    viewer = logged_in(make_user("fan@example.com"))

    async def scenario():
        socket = WebsocketCommunicator(application, path(tournament["id"]), headers=[ORIGIN, cookies(viewer)])
        connected, _ = await socket.connect()
        assert connected

        def change():
            with django_capture_on_commit_callbacks(execute=True):
                broadcast.tournament_changed(tournament["id"], "scores", event_id="e1")

        await sync_to_async(change)()
        heard = await socket.receive_json_from(timeout=2)
        await socket.send_json_to({"type": "anything"})  # ignored
        assert await socket.receive_nothing(timeout=0.2)
        await socket.disconnect()
        return heard

    assert async_to_sync(scenario)() == {"type": "changed", "topic": "scores", "event": "e1"}


@pytest.mark.django_db(transaction=True)
def test_a_socket_needs_a_session_an_allowed_origin_and_a_tournament_the_viewer_may_see(staff, club):
    draft = make_tournament(staff, club)
    stranger = logged_in(make_user("fan@example.com"))
    assert opens(draft["id"], [ORIGIN]) == (False, 4401)  # signed out
    assert opens(draft["id"], [ORIGIN, cookies(stranger)]) == (False, 4404)  # a draft is the host's
    assert opens(draft["id"], [ORIGIN, cookies(staff)])[0] is True
    assert opens(draft["id"], [(b"origin", b"https://evil.example"), cookies(staff)])[0] is False
    assert opens("00000000-0000-0000-0000-000000000000", [ORIGIN, cookies(staff)]) == (False, 4404)
    Tournament.objects.filter(pk=draft["id"]).update(status=Tournament.Status.PUBLISHED)
    assert opens(draft["id"], [ORIGIN, cookies(stranger)])[0] is True


def test_a_result_tells_the_tournament_once_committed(
    staff, club, hall, monkeypatch, django_capture_on_commit_callbacks
):
    sent = []
    monkeypatch.setattr(broadcast, "_send", lambda group, message: sent.append((group, message)))
    game = knockout(staff, club, hall)
    semi = game["semis"][0]
    with django_capture_on_commit_callbacks(execute=True):
        enter(staff, game, semi, semi.entry_a, games=[[11, 5], [11, 7], [11, 9]])
    with django_capture_on_commit_callbacks(execute=True):
        outbox.work()
    group = f"tournament.{game['cup']['id']}"
    assert sent and all(g == group and m["topic"] == "results" for g, m in sent)
    assert {m["event"] for _, m in sent} == {game["event"]["id"]}


def test_a_broadcast_with_redis_down_does_not_fail_the_change(monkeypatch, caplog):
    class Down:
        async def group_send(self, group, message):
            raise ConnectionError("redis is down")

    monkeypatch.setattr(broadcast, "get_channel_layer", lambda: Down())
    broadcast._send("tournament.x", {"type": "changed", "topic": "scores", "event": None})
    assert "Could not broadcast" in caplog.text
    with pytest.raises(ValueError):
        broadcast.tournament_changed("x", "secrets")


def test_a_new_outbox_job_wakes_a_celery_worker_after_commit_and_only_once(
    settings, monkeypatch, django_capture_on_commit_callbacks
):
    from outbox import tasks

    woken = []
    monkeypatch.setattr(tasks.work, "apply_async", lambda **kw: woken.append(kw))
    settings.REDIS_URL = ""
    with django_capture_on_commit_callbacks(execute=True):
        outbox.enqueue("test.kind", "quiet")
    assert woken == []  # no Redis: the polling worker does it
    settings.REDIS_URL = "redis://redis:6379/0"
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        outbox.enqueue("test.kind", "one")
        outbox.enqueue("test.kind", "one")  # the same job
    assert len(callbacks) == 1 and len(woken) == 1

    def broker_down(**kw):
        raise ConnectionError("no broker")

    monkeypatch.setattr(tasks.work, "apply_async", broker_down)
    with django_capture_on_commit_callbacks(execute=True):
        outbox.enqueue("test.kind", "two")  # the job is written; the sweep will find it
    assert Job.objects.filter(key="two", status=Job.Status.PENDING).exists()


def test_the_celery_task_does_the_due_jobs(monkeypatch):
    from outbox import tasks

    done = []
    monkeypatch.setitem(outbox.HANDLERS, "test.kind", lambda payload: done.append(payload["n"]))
    outbox.enqueue("test.kind", "a", {"n": 1})
    outbox.enqueue("test.kind", "b", {"n": 2})
    assert tasks.work.apply().get() == 2
    assert done == [1, 2]
    assert tasks.work.apply().get() == 0  # nothing done twice


def test_logs_are_one_json_object_per_line_with_the_request_id():
    record = logging.LogRecord("api", logging.WARNING, __file__, 1, "Seat %s taken", ("A1",), None)
    record.status = 409
    token = request_id_var.set("req-12345678")
    try:
        RequestIdFilter().filter(record)
    finally:
        request_id_var.reset(token)
    line = json.loads(JsonFormatter().format(record))
    assert line["message"] == "Seat A1 taken" and line["level"] == "WARNING"
    assert line["request_id"] == "req-12345678" and line["status"] == 409


def test_each_request_is_logged_once_without_its_query_string(client, caplog):
    with caplog.at_level(logging.INFO, logger="request"):
        response = client.get("/api/v1/auth/me/?token=secret", HTTP_X_REQUEST_ID="trace-0001")
    (record,) = [r for r in caplog.records if r.name == "request"]
    assert response["X-Request-ID"] == "trace-0001"
    assert record.path == "/api/v1/auth/me/" and record.status == response.status_code
    assert record.request_id == "trace-0001" and "secret" not in record.getMessage()


def test_ready_checks_redis_when_it_is_configured(client, settings, monkeypatch):
    from core import views

    settings.REDIS_URL = "redis://redis:6379/0"
    monkeypatch.setattr(views, "_redis_answers", lambda: False)
    response = client.get("/health/ready")
    assert response.status_code == 503 and response.json()["checks"] == {"database": "ok", "redis": "down"}
    monkeypatch.setattr(views, "_redis_answers", lambda: True)
    assert client.get("/health/ready").json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}
