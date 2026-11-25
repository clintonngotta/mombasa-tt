"""Feedback forms (REQ-055, TASK-131): the builder, templates, sending to a tournament's attendees,
answering once and editing until it closes, totals, the CSV export, and anonymity."""

import csv
import io
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from competitions.models import Entry, EntryPlayer, Event, Tournament
from feedback.models import FeedbackForm, FeedbackRecipient, FeedbackResponse
from notifications.models import Notification
from profiles.models import PlayerProfile
from reservations.models import TournamentUmpire

from .helpers import logged_in, make_user
from .test_roles import ORGS
from .test_tournaments import add_event, make_tournament

pytestmark = pytest.mark.django_db

SECTIONS = [
    {
        "title": "The day",
        "questions": [
            {"kind": "rating", "text": "How was the tournament?", "required": True},
            {
                "kind": "single",
                "text": "How did you hear about it?",
                "choices": [{"text": "A friend"}, {"text": "My club"}, {"text": "Coast TT"}],
            },
            {
                "kind": "multiple",
                "text": "What should we keep?",
                "choices": [{"text": "The venue"}, {"text": "The schedule"}],
            },
            {"kind": "yes_no", "text": "Would you come again?", "required": True},
            {"kind": "number", "text": "How many matches did you play?"},
        ],
    },
    {
        "title": "In your words",
        "questions": [
            {"kind": "short_text", "text": "One word for the day", "help": "Just one"},
            {"kind": "long_text", "text": "What should change?"},
        ],
    },
]


def forms_url(club, form=None, tail=""):
    return f"{ORGS}{club.id}/feedback-forms/" + (f"{form['id']}/{tail}" if form else "")


def mine(form):
    return f"/api/v1/feedback-forms/{form['id']}/"


def soon(days):
    return (timezone.now() + timedelta(days=days)).isoformat()


def by_text(form) -> dict:
    return {q["text"]: q for section in form["sections"] for q in section["questions"]}


def choice(question, text) -> str:
    return next(c["id"] for c in question["choices"] if c["text"] == text)


@pytest.fixture
def world(club, staff):
    """A tournament with two accepted entrants and a pending one, an umpire, a listed guest and an
    outsider."""
    tournament = make_tournament(staff, club)
    add_event(staff, tournament)
    event = Event.objects.get(tournament_id=tournament["id"])
    Tournament.objects.filter(pk=tournament["id"]).update(status=Tournament.Status.COMPLETED)
    people = {
        name: make_user(f"{name}@example.com", display_name=name.title())
        for name in ("ann", "ben", "pending", "umpire", "guest", "outsider")
    }
    for name, state in (("ann", "accepted"), ("ben", "accepted"), ("pending", "pending")):
        entry = Entry.objects.create(event=event, status=state, entered_by=people[name])
        EntryPlayer.objects.create(entry=entry, event=event, user=people[name], live=True)
    TournamentUmpire.objects.create(tournament_id=tournament["id"], user=people["umpire"])
    PlayerProfile.objects.update_or_create(user=people["guest"], defaults={"directory_opt_in": True})
    made = {
        "club": club,
        "staff": staff,
        "tournament": tournament,
        "users": people,
        **{name: logged_in(user) for name, user in people.items()},
    }
    cache.clear()  # the logins above used up the login allowance
    return made


def draft(world, **extra) -> dict:
    body = {"title": "How was it?", "tournament_id": world["tournament"]["id"], "sections": SECTIONS, **extra}
    made = world["staff"].post(forms_url(world["club"]), body, format="json")
    assert made.status_code == 201, made.json()
    return made.json()


def sent(world, **extra) -> dict:
    form = draft(world, **extra)
    out = world["staff"].post(forms_url(world["club"], form, "send/"), {"closes_at": soon(7)}, format="json")
    assert out.status_code == 200, out.json()
    return out.json()


def answers(form, **changes) -> dict:
    asked = by_text(form)
    given = {
        asked["How was the tournament?"]["id"]: 4,
        asked["How did you hear about it?"]["id"]: choice(asked["How did you hear about it?"], "My club"),
        asked["What should we keep?"]["id"]: [choice(asked["What should we keep?"], "The venue")],
        asked["Would you come again?"]["id"]: True,
        asked["How many matches did you play?"]["id"]: 3,
        asked["One word for the day"]["id"]: "Smooth",
        asked["What should change?"]["id"]: "More umpires on day two.",
    }
    for text, value in changes.items():
        given[asked[text]["id"]] = value
    return {"answers": given}


def test_the_builder_keeps_sections_and_questions_in_order_with_ids(world):
    club, staff = world["club"], world["staff"]
    form = draft(world)
    assert [s["title"] for s in form["sections"]] == ["The day", "In your words"]
    asked = by_text(form)
    assert len({q["id"] for q in asked.values()}) == 7
    assert asked["One word for the day"]["help"] == "Just one"
    assert (
        asked["How was the tournament?"]["required"] is True
        and asked["What should change?"]["required"] is False
    )
    assert [c["text"] for c in asked["What should we keep?"]["choices"]] == ["The venue", "The schedule"]

    # Editing reorders and keeps the ids sent back; a question without one is new.
    kept = asked["Would you come again?"]
    changed = staff.patch(
        forms_url(club, form),
        {"sections": [{"title": "Short", "questions": [kept, {"kind": "rating", "text": "The venue?"}]}]},
        format="json",
    )
    assert changed.status_code == 200, changed.json()
    questions = changed.json()["sections"][0]["questions"]
    assert questions[0]["id"] == kept["id"] and questions[1]["id"] != kept["id"]

    # Bad questions are refused.
    for bad in (
        {"kind": "single", "text": "Pick", "choices": [{"text": "Only one"}]},
        {"kind": "single", "text": "Pick", "choices": [{"text": "Same"}, {"text": "same"}]},
        {"kind": "essay", "text": "Unknown kind"},
        {"kind": "rating", "text": ""},
    ):
        refused = staff.patch(forms_url(club, form), {"sections": [{"questions": [bad]}]}, format="json")
        assert refused.status_code == 400, bad
    too_many = [{"questions": [{"kind": "rating", "text": f"Q{n}"} for n in range(61)]}]
    assert staff.patch(forms_url(club, form), {"sections": too_many}, format="json").status_code == 400
    assert staff.patch(forms_url(club, form), {"owner": "x"}, format="json").status_code == 400


def test_templates_are_reused_and_never_sent(world):
    club, staff = world["club"], world["staff"]
    template = staff.post(
        forms_url(club), {"title": "Standard", "is_template": True, "sections": SECTIONS}, format="json"
    )
    assert template.status_code == 201, template.json()
    template = template.json()
    assert template["tournament"] is None
    listed = staff.get(forms_url(club) + "?templates=1").json()
    assert [f["title"] for f in listed] == ["Standard"]
    send = staff.post(forms_url(club, template, "send/"), {"closes_at": soon(7)}, format="json")
    assert send.status_code == 409 and send.json()["code"] == "is_template"
    # A template has no tournament; a form has one.
    both = {"title": "x", "is_template": True, "tournament_id": world["tournament"]["id"]}
    assert staff.post(forms_url(club), both, format="json").status_code == 400
    assert staff.post(forms_url(club), {"title": "x"}, format="json").status_code == 400

    made = staff.post(
        forms_url(club),
        {"title": "After the Open", "tournament_id": world["tournament"]["id"], "copy_from": template["id"]},
        format="json",
    ).json()
    assert list(by_text(made)) == list(by_text(template))
    assert not {q["id"] for q in by_text(made).values()} & {q["id"] for q in by_text(template).values()}
    per_tournament = staff.get(forms_url(club) + f"?tournament={world['tournament']['id']}").json()
    assert [f["title"] for f in per_tournament] == ["After the Open"]
    assert staff.delete(forms_url(club, template)).status_code == 204


def test_only_the_hosts_competition_staff_build_and_read(world):
    form = draft(world)
    for who in ("ann", "outsider"):
        client = world[who]
        assert client.get(forms_url(world["club"])).status_code == 403
        assert client.post(forms_url(world["club"]), {"title": "x"}, format="json").status_code == 403
        for tail in ("", "totals/", "export.csv"):
            assert client.get(forms_url(world["club"], form, tail)).status_code == 403
        assert (
            client.post(
                forms_url(world["club"], form, "send/"), {"closes_at": soon(1)}, format="json"
            ).status_code
            == 403
        )
    # A draft isn't there for anyone to answer.
    assert world["ann"].get(mine(form)).status_code == 404


def test_sending_fixes_who_is_asked_and_tells_them(world):
    club, staff, users = world["club"], world["staff"], world["users"]
    empty = draft(world, sections=[])
    assert (
        staff.post(forms_url(club, empty, "send/"), {"closes_at": soon(7)}, format="json").json()["code"]
        == "no_questions"
    )
    nobody = draft(world, to_entrants=False)
    assert (
        staff.post(forms_url(club, nobody, "send/"), {"closes_at": soon(7)}, format="json").json()["code"]
        == "no_recipients"
    )
    refused = staff.post(
        forms_url(club),
        {"title": "x", "tournament_id": world["tournament"]["id"], "guest_ids": [str(users["outsider"].id)]},
        format="json",
    )
    assert refused.status_code == 400 and "guest_ids" in refused.json()["fields"]

    form = draft(world, to_umpires=True, guest_ids=[str(users["guest"].id)])
    past = staff.post(forms_url(club, form, "send/"), {"closes_at": soon(-1)}, format="json")
    assert past.status_code == 400
    out = staff.post(forms_url(club, form, "send/"), {"closes_at": soon(7)}, format="json").json()
    assert out["status"] == "sent" and out["open"] is True and out["recipients"] == 4
    asked = set(
        FeedbackRecipient.objects.filter(form_id=form["id"]).values_list("user__display_name", flat=True)
    )
    assert asked == {"Ann", "Ben", "Umpire", "Guest"}  # not the pending entrant, the staff or the outsider
    told = set(
        Notification.objects.filter(subject=f"feedback:{form['id']}").values_list(
            "recipient__display_name", flat=True
        )
    )
    assert told == asked
    # Once sent it can't be sent again, changed or removed.
    assert (
        staff.post(forms_url(club, form, "send/"), {"closes_at": soon(7)}, format="json").json()["code"]
        == "form_sent"
    )
    assert staff.patch(forms_url(club, form), {"title": "New"}, format="json").json()["code"] == "form_sent"
    assert staff.delete(forms_url(club, form)).json()["code"] == "form_sent"

    assert [f["title"] for f in world["ann"].get("/api/v1/me/feedback-forms/").json()] == ["How was it?"]
    for other in ("pending", "outsider"):
        assert world[other].get("/api/v1/me/feedback-forms/").json() == []
        assert world[other].get(mine(form)).status_code == 404
        assert world[other].put(mine(form), answers(out), format="json").status_code == 404
    assert FeedbackResponse.objects.count() == 0


def test_attendees_answer_once_and_edit_until_it_closes(world):
    form = sent(world)
    ann = world["ann"]
    seen = ann.get(mine(form)).json()
    assert seen["open"] is True and seen["answered"] is False and seen["my_answers"] == {}

    # Required questions, kinds and choices are enforced; nothing is stored on a refusal.
    asked = by_text(form)
    missing = answers(form)
    del missing["answers"][asked["How was the tournament?"]["id"]]
    refused = ann.put(mine(form), missing, format="json")
    assert refused.status_code == 400
    # The refusal names the question, so the form can show the message beside it.
    assert refused.json()["fields"] == {asked["How was the tournament?"]["id"]: "Answer this question."}
    for text, bad in (
        ("How was the tournament?", 6),
        ("How was the tournament?", True),
        ("How did you hear about it?", "not-a-choice"),
        ("What should we keep?", "The venue"),
        ("Would you come again?", "yes"),
        ("How many matches did you play?", "lots"),
        ("One word for the day", "x" * 301),
    ):
        assert ann.put(mine(form), answers(form, **{text: bad}), format="json").status_code == 400, (
            text,
            bad,
        )
    unknown = answers(form)
    unknown["answers"]["0" * 12] = 1
    assert ann.put(mine(form), unknown, format="json").status_code == 400
    assert ann.put(mine(form), {**answers(form), "name": "Ann"}, format="json").status_code == 400
    assert FeedbackResponse.objects.count() == 0

    saved = ann.put(mine(form), answers(form), format="json")
    assert saved.status_code == 200, saved.json()
    assert saved.json()["answered"] is True
    assert saved.json()["my_answers"][asked["How was the tournament?"]["id"]] == 4
    # Answering again changes the same response.
    again = ann.put(mine(form), answers(form, **{"How was the tournament?": 5}), format="json").json()
    assert again["my_answers"][asked["How was the tournament?"]["id"]] == 5
    assert FeedbackResponse.objects.count() == 1
    assert ann.get("/api/v1/me/feedback-forms/").json()[0]["answered"] is True
    # Another attendee doesn't see Ann's answers.
    assert world["ben"].get(mine(form)).json()["my_answers"] == {}

    # After closing, nobody answers or edits; staff can open it again by moving the closing time.
    FeedbackForm.objects.filter(pk=form["id"]).update(
        opens_at=timezone.now() - timedelta(days=1), closes_at=timezone.now() - timedelta(minutes=1)
    )
    assert ann.put(mine(form), answers(form), format="json").json()["code"] == "form_closed"
    assert world["ben"].put(mine(form), answers(form), format="json").json()["code"] == "form_closed"
    assert ann.get(mine(form)).json()["open"] is False
    assert ann.get("/api/v1/me/feedback-forms/").json() == []
    reopened = world["staff"].post(
        forms_url(world["club"], form, "closing/"), {"closes_at": soon(2)}, format="json"
    )
    assert reopened.status_code == 200 and reopened.json()["open"] is True
    assert world["ben"].put(mine(form), answers(form), format="json").status_code == 200


def test_totals_match_the_answers(world):
    form = sent(world)
    asked = by_text(form)
    keep = asked["What should we keep?"]
    world["ann"].put(mine(form), answers(form), format="json")
    world["ben"].put(
        mine(form),
        answers(
            form,
            **{
                "How was the tournament?": 2,
                "What should we keep?": [choice(keep, "The venue"), choice(keep, "The schedule")],
                "Would you come again?": False,
                "How many matches did you play?": 5,
                "One word for the day": "",
                "What should change?": "",
            },
        ),
        format="json",
    )
    totals = world["staff"].get(forms_url(world["club"], form, "totals/")).json()
    assert (totals["responses"], totals["recipients"]) == (2, 2)
    rows = {row["text"]: row for row in totals["questions"]}
    rating = rows["How was the tournament?"]
    assert rating["average"] == 3.0 and rating["answered"] == 2
    assert [c["count"] for c in rating["counts"]] == [0, 1, 0, 1, 0]
    assert {c["label"]: c["count"] for c in rows["How did you hear about it?"]["counts"]} == {
        "A friend": 0,
        "My club": 2,
        "Coast TT": 0,
    }
    assert {c["label"]: c["count"] for c in rows["What should we keep?"]["counts"]} == {
        "The venue": 2,
        "The schedule": 1,
    }
    assert {c["label"]: c["count"] for c in rows["Would you come again?"]["counts"]} == {"Yes": 1, "No": 1}
    assert rows["How many matches did you play?"]["average"] == 4.0
    assert (
        rows["One word for the day"]["texts"] == ["Smooth"] and rows["One word for the day"]["answered"] == 1
    )
    assert rows["What should change?"]["texts"] == ["More umpires on day two."]


def export(world, form) -> list[list[str]]:
    response = world["staff"].get(forms_url(world["club"], form, "export.csv"))
    assert response.status_code == 200 and response["Content-Type"].startswith("text/csv")
    return list(csv.reader(io.StringIO(response.content.decode())))


def test_a_named_form_exports_who_answered_and_escapes_formulas(world):
    form = sent(world)
    world["ann"].put(
        mine(form), answers(form, **{"What should change?": '=HYPERLINK("http://x")'}), format="json"
    )
    rows = export(world, form)
    assert rows[0][:3] == ["Name", "Answered", "How was the tournament?"]
    assert rows[1][0] == "Ann" and rows[1][2] == "4"
    assert "My club" in rows[1] and "The venue" in rows[1] and "Yes" in rows[1]
    assert rows[1][-1].startswith("'=")  # a spreadsheet won't run it


def test_an_anonymous_form_never_says_who_answered_what(world):
    form = sent(world, anonymous=True)
    users = world["users"]
    world["ann"].put(mine(form), answers(form, **{"One word for the day": "Quick"}), format="json")
    world["ben"].put(mine(form), answers(form, **{"One word for the day": "Tidy"}), format="json")
    # Each still finds and edits their own answers.
    asked = by_text(form)
    word = asked["One word for the day"]["id"]
    assert world["ann"].get(mine(form)).json()["my_answers"][word] == "Quick"
    world["ann"].put(mine(form), answers(form, **{"One word for the day": "Brisk"}), format="json")
    assert FeedbackResponse.objects.count() == 2

    # Nothing stored links a response to a person, and no time is kept.
    for response in FeedbackResponse.objects.all():
        assert (
            response.respondent_id is None and response.submitted_at is None and response.updated_at is None
        )
        for user in (users["ann"], users["ben"]):
            assert str(user.id) not in response.owner_key

    # Nothing staff can fetch names anyone.
    staff, club = world["staff"], world["club"]
    names = ("Ann", "Ben", "ann@example.com", "ben@example.com", str(users["ann"].id), str(users["ben"].id))
    rows = export(world, form)
    assert rows[0][0] == "How was the tournament?" and len(rows) == 3
    for path in ("", "totals/", "export.csv"):
        body = staff.get(forms_url(club, form, path)).content.decode()
        assert not any(name in body for name in names), path
    assert sorted(staff.get(forms_url(club, form, "totals/")).json()["questions"][5]["texts"]) == [
        "Brisk",
        "Tidy",
    ]
