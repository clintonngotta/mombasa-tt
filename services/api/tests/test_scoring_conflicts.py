"""One device per sheet, take-over, and what a cut-off device reports (REQ-013, REQ-015, TASK-026): a
stale device can't overwrite accepted data, and what it held stays visible to the organizers."""

import uuid

import pytest

from facilities.models import Table
from reservations.models import Hold
from scoring.models import ScoreAssignment, ScoreConflict, ScoreEvent

from .helpers import logged_in, make_user
from .test_roles import add_member
from .test_tournaments import url
from .test_umpire_scoring import START, assign, final, match_url, point, scorers, umpire  # noqa: F401

pytestmark = pytest.mark.django_db


class Device:
    """A phone or tablet scoring a sheet: its own id on every request, and the assignment it holds."""

    def __init__(self, client, scorecard_id, label: str):
        self.client = client
        self.id = str(uuid.uuid4())
        self.label = label
        self.path = f"/api/v1/scorecards/{scorecard_id}/"
        self.assignment_id = None
        self.sequence = 0

    @property
    def headers(self) -> dict:
        return {"HTTP_X_DEVICE_ID": self.id}

    def open(self) -> dict:
        sheet = self.client.get(self.path, **self.headers)
        assert sheet.status_code == 200, sheet.json()
        self.assignment_id = sheet.json()["assignment_id"]
        self.sequence = sheet.json()["revision"]
        return sheet.json()

    def take(self, take_over=False, expect=200) -> dict:
        body = {"device_id": self.id, "label": self.label, "take_over": take_over}
        response = self.client.post(self.path + "device/", body, format="json", **self.headers)
        assert response.status_code == expect, response.json()
        if expect == 200:
            self.assignment_id = response.json()["assignment_id"]
            self.sequence = response.json()["revision"]
        return response.json()

    def envelope(self, event: dict) -> dict:
        self.sequence += 1
        return {"id": str(uuid.uuid4()), "sequence": self.sequence, "event": event}

    def send(self, *events: dict, expect=200) -> dict:
        body = {"assignment_id": self.assignment_id, "events": [self.envelope(e) for e in events]}
        response = self.client.post(self.path + "events/", body, format="json", **self.headers)
        assert response.status_code == expect, response.json()
        return response.json()

    def confirm(self, expect=200) -> dict:
        body = {"assignment_id": self.assignment_id, "revision": self.sequence}
        response = self.client.post(self.path + "confirm/", body, format="json", **self.headers)
        assert response.status_code == expect, response.json()
        return response.json()

    def report(self, events: list[dict], expect=201, report_id=None, client=None) -> dict:
        body = {
            "id": report_id or str(uuid.uuid4()),
            "assignment_id": self.assignment_id,
            "device_id": self.id,
            "device_label": self.label,
            "events": events,
        }
        response = (client or self.client).post(self.path + "conflicts/", body, format="json")
        assert response.status_code == expect, response.json()
        return response.json()


def sheet_id(client, game) -> str:
    return client.get(match_url(game)).json()["scoring"]["scorecard_id"]


def overview(staff, game) -> dict:
    response = staff.get(url(game["cup"]) + "scoring/")
    assert response.status_code == 200, response.json()
    return response.json()


def test_one_device_scores_a_sheet_and_another_has_to_take_it_over(staff, final, umpire):  # noqa: F811
    assign(staff, final, umpire)
    as_umpire = logged_in(umpire)
    card = sheet_id(as_umpire, final)
    phone, tablet = Device(as_umpire, card, "Phone"), Device(as_umpire, card, "Tablet")

    assert phone.open()["device"] == {"held": False, "here": False, "label": "", "since": None}
    taken = phone.take()["device"]
    assert (taken["held"], taken["here"], taken["label"]) == (True, True, "Phone")
    phone.send(START, point("a"))

    # The tablet sees the sheet but is told another device has it, and can't score or confirm.
    seen = tablet.open()["device"]
    assert (seen["held"], seen["here"], seen["label"]) == (True, False, "Phone")
    assert tablet.send(point("b"), expect=409)["code"] == "other_device"
    assert tablet.confirm(expect=409)["code"] == "other_device"
    assert tablet.take(expect=409)["code"] == "other_device"
    # A request with no device id at all is no better than one from the wrong device.
    bare = as_umpire.post(
        tablet.path + "events/",
        {"assignment_id": tablet.assignment_id, "events": [tablet.envelope(point("b"))]},
        format="json",
    )
    assert bare.json()["code"] == "other_device"
    assert ScoreEvent.objects.count() == 2

    # Taking over is explicit. It issues a new assignment id: the phone is cut off from that moment.
    tablet.take(take_over=True)
    assert tablet.assignment_id != phone.assignment_id and tablet.sequence == 2
    assert phone.send(point("a"), expect=409)["code"] == "stale_assignment"
    phone.sequence = 2
    assert phone.confirm(expect=409)["code"] == "stale_assignment"
    assert tablet.send(point("b"))["state"]["points"] == [1, 1]
    # The phone, reloaded, holds the new assignment id but is still not the device: it stays cut off.
    assert phone.open()["device"]["here"] is False
    assert phone.send(point("a"), expect=409)["code"] == "other_device"
    assert [e.sequence for e in ScoreEvent.objects.order_by("sequence")] == [1, 2, 3]

    steps = list(ScoreAssignment.objects.values_list("kind", "device_label", "revision"))
    assert steps == [("assigned", "", 0), ("device", "Phone", 0), ("take_over", "Tablet", 2)]
    # A new assignment by staff frees the sheet from any device.
    assign(staff, final, umpire)
    assert tablet.open()["device"]["held"] is False


def test_what_a_cut_off_device_held_is_reported_and_stays_for_the_organizers(staff, club, final, umpire):  # noqa: F811
    assign(staff, final, umpire)
    as_umpire = logged_in(umpire)
    card = sheet_id(as_umpire, final)
    phone = Device(as_umpire, card, "Phone")
    phone.open()
    phone.take()
    phone.send(START, point("a"))
    # The phone goes on offline: two more points it never manages to send.
    unsent = [phone.envelope(point("a")), phone.envelope(point("a"))]

    # The organizers give the match to somebody else, who scores a different point.
    other = make_user("other.umpire@example.com", display_name="Omar Other")
    add_member(club, other, scorers(club))
    assign(staff, final, other)
    as_other = logged_in(other)
    laptop = Device(as_other, card, "Laptop")
    laptop.open()
    laptop.take()
    laptop.send(point("b"))

    # The phone can no longer reach the sheet, but it can still say what it held. Twice is once.
    assert as_umpire.get(phone.path, **phone.headers).status_code == 404
    report_id = str(uuid.uuid4())
    phone.report(unsent[:1], report_id=report_id)
    phone.report(unsent[:1], report_id=report_id)
    assert [len(kept.events) for kept in ScoreConflict.objects.all()] == [1]
    # The same report again with more in it (the first reply was lost and the device has since been
    # cut off once more): what is new is added, nothing is dropped behind the id already known.
    phone.report(unsent, report_id=report_id)
    assert [len(kept.events) for kept in ScoreConflict.objects.all()] == [2]
    # Nobody else can add to it, and what is reported has to be a score event.
    assert (
        as_other.post(
            phone.path + "conflicts/",
            {"id": report_id, "events": [laptop.envelope(point("b"))]},
            format="json",
        ).json()["code"]
        == "conflict_exists"
    )
    laptop.sequence -= 1
    junk = {"id": str(uuid.uuid4()), "sequence": 1, "event": {"type": "point", "side": "<b>" * 20}}
    assert (
        as_umpire.post(
            phone.path + "conflicts/", {"id": str(uuid.uuid4()), "events": [junk]}, format="json"
        ).status_code
        == 400
    )
    # Nothing about the score changed.
    assert laptop.open()["state"]["points"] == [1, 1]
    # Somebody who never held the sheet can't report, and learns nothing about it.
    stranger = logged_in(make_user("stranger@example.com"))
    phone.report(unsent, expect=404, client=stranger)
    nobody = phone.path.replace(card, str(uuid.uuid4())) + "conflicts/"
    assert (
        as_umpire.post(nobody, {"id": str(uuid.uuid4()), "events": unsent}, format="json").status_code == 404
    )

    shown = overview(staff, final)
    (sheet,) = shown["sheets"]
    assert (sheet["status"], sheet["umpire"], sheet["device_label"], sheet["revision"]) == (
        "in_progress",
        "Omar Other",
        "Laptop",
        3,
    )
    assert sheet["points"] == [1, 1] and sheet["sheet"]["label"] == "Final"
    assert [(step["kind"], step["umpire"], step["device_label"]) for step in sheet["history"]] == [
        ("assigned", "Zuri Umpire", ""),
        ("device", "Zuri Umpire", "Phone"),
        ("assigned", "Omar Other", ""),
        ("device", "Omar Other", "Laptop"),
    ]
    (conflict,) = shown["conflicts"]
    assert (conflict["reported_by"], conflict["device_label"], conflict["resolved_at"]) == (
        "Zuri Umpire",
        "Phone",
        None,
    )
    assert [(e["sequence"], e["event"]) for e in conflict["events"]] == [(3, point("a")), (4, point("a"))]
    # Beside it, what the official stream holds at those places: one point for the other side.
    assert conflict["accepted"] == [{"sequence": 3, "event": point("b")}]

    # Only competition staff see this page or close a report, and closing needs a note.
    for client in (as_umpire, as_other, stranger):
        assert client.get(url(final["cup"]) + "scoring/").status_code == 403
    resolve = url(final["cup"]) + f"scoring/conflicts/{conflict['id']}/resolve/"
    assert as_other.post(resolve, {"note": "mine"}, format="json").status_code == 403
    assert staff.post(resolve, {}, format="json").status_code == 400
    done = staff.post(resolve, {"note": "Both players agree with the official score."}, format="json")
    assert done.status_code == 200
    (closed,) = done.json()["conflicts"]
    assert closed["resolved_by"] == "Club Admin" and closed["resolution"].startswith("Both players")
    assert staff.post(resolve, {"note": "again"}, format="json").json()["code"] == "already_resolved"
    assert ScoreConflict.objects.count() == 1  # kept on record


def test_a_finished_sheet_waits_visibly_for_its_confirmation(staff, final, umpire):  # noqa: F811
    assign(staff, final, umpire)
    as_umpire = logged_in(umpire)
    phone = Device(as_umpire, sheet_id(as_umpire, final), "Phone")
    phone.open()
    assert overview(staff, final) == {"sheets": [], "conflicts": [], "reservations": []}  # nothing yet
    # The match goes to a table: from now on the table and both players are held.
    table = Table.objects.create(venue=final["match"].draw.event.tournament.venue, label="Table 1")
    sent = staff.post(
        match_url(final, "dispatch/"),
        {"table_id": str(table.id), "overrides": ["check_in"], "reason": "Both at the table"},
        format="json",
    )
    assert sent.status_code == 200, sent.json()
    phone.take()
    phone.send(START, *[point("a")] * 22)
    shown = overview(staff, final)
    (waiting,) = shown["sheets"]
    assert (waiting["status"], waiting["games"], waiting["last_event_at"] is not None) == (
        "finished",
        [[11, 0], [11, 0]],
        True,
    )
    # Finished but not confirmed: the reservation is still there, and still shown (REQ-013).
    (held,) = shown["reservations"]
    assert (held["table"], len(held["people"]), held["overrides"]) == ("Table 1", 2, ["check_in"])
    assert Hold.objects.filter(active=True).count() == 3
    phone.confirm()
    after = overview(staff, final)
    assert after["sheets"] == [] and after["reservations"] == []
    assert not Hold.objects.filter(active=True).exists()


def test_the_first_device_to_score_an_unheld_sheet_holds_it(staff, final, umpire):  # noqa: F811
    assign(staff, final, umpire)
    as_umpire = logged_in(umpire)
    card = sheet_id(as_umpire, final)
    phone, tablet = Device(as_umpire, card, "Phone"), Device(as_umpire, card, "Tablet")
    phone.open()
    tablet.open()
    # Neither asked for the sheet; the phone's first events take it.
    phone.send(START)
    assert tablet.send(point("a"), expect=409)["code"] == "other_device"
    assert phone.open()["device"]["here"] is True
    assert ScoreEvent.objects.count() == 1


def test_a_report_about_a_replaced_draw_is_still_shown(staff, club, umpire):  # noqa: F811
    from competitions.models import Match

    from .test_draws import draw_url, fill
    from .test_tournaments import add_event, do, make_tournament
    from .test_venues import make_venue

    tournament = make_tournament(staff, club, make_venue(staff, club))
    tournament = add_event(staff, tournament, name="Singles", format="knockout")
    tournament = do(staff, tournament, "publish")
    event = tournament["events"][0]
    fill(staff, tournament, event, 2)
    staff.post(draw_url(tournament, event, "preview"), {}, format="json")
    staff.post(draw_url(tournament, event, "publish"), {}, format="json")
    game = {"cup": tournament, "event": event, "match": Match.objects.get(draw__event_id=event["id"])}
    assign(staff, game, umpire)
    as_umpire = logged_in(umpire)
    phone = Device(as_umpire, sheet_id(as_umpire, game), "Phone")
    phone.open()
    phone.report([phone.envelope(point("a"))])
    staff.post(draw_url(tournament, event, "preview"), {}, format="json")
    assert staff.post(draw_url(tournament, event, "publish"), {}, format="json").status_code == 200
    shown = overview(staff, game)
    assert len(shown["conflicts"]) == 1 and shown["sheets"] == []
