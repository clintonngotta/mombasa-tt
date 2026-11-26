"""Meetings beyond the core (REQ-046, TASK-109): notices to invitees, agenda documents, the check-in
window, minutes with decisions, action items and the next meeting, approval and amendments, and a
person's action items across organizations."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from notifications.models import Notification
from organizations.models import Representative, Role
from regions.models import ActionItem, Meeting, MeetingDocument

from .helpers import logged_in, make_user
from .test_representatives import make_body
from .test_roles import ORGS, add_member

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
ME = "/api/v1/me/"


def soon(hours):
    return (timezone.now() + timedelta(hours=hours)).isoformat()


def url(club, meeting_id="", path=""):
    return f"{ORGS}{club.id}/meetings/" + (f"{meeting_id}/{path}" if meeting_id else "")


def pdf(name="paper.pdf", content=PDF):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


def titles(user) -> list[str]:
    return sorted(Notification.objects.filter(recipient=user).values_list("title", flat=True))


@pytest.fixture
def people(club, admin):
    """A governance officer, a secretary, two invited members, and a member of another club."""
    governance = Role.objects.create(organization=club, name="Governance", permissions=["governance.manage"])
    users = {
        name: make_user(f"{name}@example.com", display_name=name.title())
        for name in ("officer", "secretary", "amina", "baraka", "outsider")
    }
    add_member(club, users["officer"], governance)
    for name in ("secretary", "amina", "baraka"):
        add_member(club, users[name])
    return {"admin": logged_in(admin), **{n: logged_in(u) for n, u in users.items()}, "users": users}


def draft(club, people, **extra) -> dict:
    made = people["officer"].post(
        url(club),
        {
            "title": "AGM",
            "kind": "general",
            "audience": "members",
            "starts_at": soon(2),
            "ends_at": soon(4),
            "agenda": [{"title": "Accounts", "presenter": "Treasurer"}, {"title": "Coast Open"}],
            "secretary_id": str(people["users"]["secretary"].id),
            **extra,
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    return made.json()


def published(club, people, **extra) -> dict:
    meeting = draft(club, people, **extra)
    out = people["officer"].post(url(club, meeting["id"], "publish/"), format="json")
    assert out.status_code == 200, out.json()
    return out.json()


def start(meeting, *, over=False):
    now = timezone.now()
    Meeting.objects.filter(pk=meeting["id"]).update(
        starts_at=now - timedelta(hours=2),
        ends_at=now - timedelta(hours=1) if over else now + timedelta(hours=1),
    )


def test_invitees_are_told_of_publication_changes_and_cancellation(club, people):
    amina = people["users"]["amina"]
    meeting = published(club, people)
    assert titles(amina) == ["You're invited: AGM"]
    assert titles(people["users"]["officer"]) == []  # whoever did it isn't told
    assert titles(people["users"]["outsider"]) == []
    alert = Notification.objects.get(recipient=amina)
    assert alert.link == f"/meetings/{club.id}/{meeting['id']}" and alert.category == "meeting"

    # Each agenda item keeps its id through a revision, and the change is a new notice.
    first, second = meeting["agenda"]
    assert first["id"] and second["id"] and first["id"] != second["id"]
    revised = people["officer"].patch(
        url(club, meeting["id"]),
        {"agenda": [{"id": second["id"], "title": "Coast Open 2027"}, {"title": "Any other business"}]},
        format="json",
    )
    assert revised.status_code == 200, revised.json()
    agenda = revised.json()["agenda"]
    assert agenda[0]["id"] == second["id"] and agenda[1]["id"] not in (first["id"], second["id"])
    assert revised.json()["revision"] == 1
    assert titles(amina) == ["AGM has changed", "You're invited: AGM"]
    # A change that changes nothing isn't a notice.
    same = people["officer"].patch(url(club, meeting["id"]), {"location": ""}, format="json")
    assert same.json()["revision"] == 1

    people["officer"].post(url(club, meeting["id"], "cancel/"), {"reason": "Venue closed"}, format="json")
    assert "Cancelled: AGM" in titles(amina)
    live = Notification.objects.filter(recipient=amina, superseded=False)
    assert [n.title for n in live] == ["Cancelled: AGM"]


def test_an_agenda_item_links_only_to_a_tournament_the_host_may_name(club, people):
    import uuid

    refused = people["officer"].post(
        url(club),
        {
            "title": "x",
            "starts_at": soon(2),
            "ends_at": soon(3),
            "agenda": [{"title": "Planning", "tournament": str(uuid.uuid4())}],
        },
        format="json",
    )
    assert refused.status_code == 400 and "agenda" in refused.json()["fields"]


def test_documents_are_pdfs_for_whoever_sees_the_meeting(club, people):
    meeting = draft(club, people)
    item = meeting["agenda"][0]["id"]
    path = url(club, meeting["id"], "documents/")
    for client in (people["amina"], people["secretary"]):
        assert client.post(path, {"title": "x", "file": pdf()}, format="multipart").status_code == 404
    not_pdf = people["officer"].post(path, {"title": "x", "file": pdf(content=b"hello")}, format="multipart")
    assert not_pdf.status_code == 400
    unknown = people["officer"].post(
        path, {"title": "x", "item": "0" * 12, "file": pdf()}, format="multipart"
    )
    assert unknown.status_code == 400 and "item" in unknown.json()["fields"]
    added = people["officer"].post(
        path, {"title": "Accounts 2026", "item": item, "file": pdf()}, format="multipart"
    )
    assert added.status_code == 201, added.json()
    document = added.json()["documents"][0]
    assert document["item"] == item and document["title"] == "Accounts 2026"
    attachment = MeetingDocument.objects.get().file_id
    link = f"/api/v1/attachments/{attachment}/url/"

    # A draft's documents are for governance staff; once published, for the invitees too.
    assert people["amina"].get(link).status_code == 404
    assert people["officer"].get(link).status_code == 200
    people["officer"].post(url(club, meeting["id"], "publish/"), format="json")
    seen = people["amina"].get(url(club, meeting["id"])).json()
    assert seen["documents"][0]["file"]["url"].startswith(f"/api/v1/attachments/{attachment}/content/")
    assert people["amina"].get(link).status_code == 200
    assert people["outsider"].get(link).status_code == 404
    assert people["amina"].get(seen["documents"][0]["file"]["url"]).status_code == 200

    # Removing the agenda item keeps the document with the meeting.
    people["officer"].patch(url(club, meeting["id"]), {"agenda": [{"title": "Other"}]}, format="json")
    assert MeetingDocument.objects.get().item == ""
    assert people["amina"].delete(url(club, meeting["id"], f"documents/{document['id']}/")).status_code == 403
    removed = people["officer"].delete(url(club, meeting["id"], f"documents/{document['id']}/"))
    assert removed.status_code == 200 and removed.json()["documents"] == []


def test_check_in_only_while_the_meeting_runs(club, people):
    meeting = published(club, people)
    path = url(club, meeting["id"], "check-in/")
    assert people["amina"].post(path, format="json").json()["code"] == "not_in_progress"
    start(meeting)
    checked = people["amina"].post(path, format="json")
    assert checked.status_code == 200 and checked.json()["me"]["attendance"] == "present"
    assert people["outsider"].post(path, format="json").status_code == 404
    start(meeting, over=True)
    assert people["baraka"].post(path, format="json").json()["code"] == "not_in_progress"


def minutes_body(meeting, people, **extra):
    return {
        "minutes": "The accounts were presented.",
        "decisions": [{"item": meeting["agenda"][0]["id"], "text": "Accounts adopted."}],
        "action_items": [
            {
                "item": meeting["agenda"][1]["id"],
                "description": "Book the hall",
                "owner_id": str(people["users"]["amina"].id),
                "due_on": "2027-01-15",
            }
        ],
        "next_meeting_at": soon(24 * 30),
        **extra,
    }


def test_minutes_are_a_draft_until_approved_then_never_change(club, people):
    meeting = published(club, people)
    path = url(club, meeting["id"], "minutes/")
    body = minutes_body(meeting, people)
    assert people["officer"].post(path, body, format="json").json()["code"] == "meeting_not_held"
    start(meeting)
    assert people["amina"].post(path, body, format="json").status_code == 403
    assert people["outsider"].post(path, body, format="json").status_code == 404
    assert people["officer"].post(path, {**body, "approved": True}, format="json").status_code == 400
    stranger = {
        **body,
        "action_items": [{"description": "x", "owner_id": str(people["users"]["outsider"].id)}],
    }
    assert people["officer"].post(path, stranger, format="json").status_code == 400

    # The secretary writes them; saving again replaces the action items rather than adding to them.
    saved = people["secretary"].post(path, body, format="json")
    assert saved.status_code == 200, saved.json()
    saved = saved.json()
    assert saved["minutes_status"] == "draft" and saved["decisions"][0]["text"] == "Accounts adopted."
    action = saved["action_items"][0]
    assert action["owner_name"] == "Amina" and action["status"] == "open" and action["mine"] is False
    assert [choice["display_name"] for choice in saved["owner_choices"]] == sorted(
        choice["display_name"] for choice in saved["owner_choices"]
    )
    again = {
        **body,
        "action_items": [{**body["action_items"][0], "id": action["id"], "description": "Book it"}],
    }
    kept = people["secretary"].post(path, again, format="json").json()["action_items"]
    assert [(a["id"], a["description"]) for a in kept] == [(action["id"], "Book it")]

    # A draft is not for the invitees, and they aren't told of an action item yet.
    seen = people["amina"].get(url(club, meeting["id"])).json()
    assert (seen["minutes"], seen["minutes_status"], seen["decisions"], seen["action_items"]) == (
        "",
        "",
        [],
        [],
    )
    assert seen["next_meeting_at"] is None and seen["owner_choices"] == []
    assert people["amina"].get(f"{ME}action-items/").json() == []
    done = url(club, meeting["id"], f"action-items/{action['id']}/")
    assert people["amina"].post(done, {"status": "done"}, format="json").status_code == 404

    # Approval: governance staff only, once the meeting is over.
    approve = path + "approve/"
    assert people["secretary"].post(approve, {}, format="json").status_code == 403
    assert people["officer"].post(approve, {}, format="json").json()["code"] == "meeting_running"
    start(meeting, over=True)
    approved = people["officer"].post(approve, {"create_next": True}, format="json")
    assert approved.status_code == 200, approved.json()
    assert approved.json()["minutes_status"] == "approved" and approved.json()["next_meeting"]
    following = Meeting.objects.get(follows_id=meeting["id"])
    assert following.status == "draft" and following.audience == "members" and following.title == "AGM"
    assert following.ends_at - following.starts_at == timedelta(hours=1)
    assert people["officer"].post(approve, {}, format="json").json()["code"] == "no_draft_minutes"

    # Now the invitees read them, and nobody changes them.
    seen = people["baraka"].get(url(club, meeting["id"])).json()
    assert seen["minutes"] == "The accounts were presented." and seen["next_meeting"] is None
    assert seen["action_items"][0]["description"] == "Book it" and seen["action_items"][0]["mine"] is False
    assert "Minutes of AGM are ready" in titles(people["users"]["baraka"])
    assert "Action for you from AGM" in titles(people["users"]["amina"])
    for client in (people["officer"], people["secretary"], people["admin"]):
        assert client.post(path, body, format="json").json()["code"] == "minutes_approved"
    assert Meeting.objects.get(pk=meeting["id"]).minutes == "The accounts were presented."

    # A correction is an amendment beside them.
    amend = path + "amendments/"
    assert people["secretary"].post(amend, {"text": "x"}, format="json").status_code == 403
    amended = people["officer"].post(amend, {"text": "The hall is booked for the 20th."}, format="json")
    assert amended.status_code == 201
    seen = people["baraka"].get(url(club, meeting["id"])).json()
    assert [a["text"] for a in seen["amendments"]] == ["The hall is booked for the 20th."]
    assert seen["amendments"][0]["by_name"] == "Officer" and seen["minutes"] == "The accounts were presented."
    assert "Minutes of AGM were amended" in titles(people["users"]["baraka"])


def test_amendments_need_approved_minutes(club, people):
    meeting = published(club, people)
    start(meeting, over=True)
    amend = url(club, meeting["id"], "minutes/amendments/")
    assert (
        people["officer"].post(amend, {"text": "x"}, format="json").json()["code"] == "minutes_not_approved"
    )


def test_owners_see_and_close_their_action_items_everywhere(club, people):
    meeting = published(club, people)
    start(meeting, over=True)
    path = url(club, meeting["id"], "minutes/")
    people["officer"].post(path, minutes_body(meeting, people), format="json")
    people["officer"].post(path + "approve/", {}, format="json")
    mine = people["amina"].get(f"{ME}action-items/").json()
    assert [(a["description"], a["meeting_title"], a["organization"]["name"]) for a in mine] == [
        ("Book the hall", "AGM", club.name)
    ]
    assert mine[0]["mine"] is True and people["baraka"].get(f"{ME}action-items/").json() == []

    action = url(club, meeting["id"], f"action-items/{mine[0]['id']}/")
    assert people["baraka"].post(action, {"status": "done"}, format="json").status_code == 403
    assert people["outsider"].post(action, {"status": "done"}, format="json").status_code == 404
    assert people["amina"].post(action, {"status": "closed"}, format="json").status_code == 400
    done = people["amina"].post(action, {"status": "done"}, format="json")
    assert done.status_code == 200 and done.json()["action_items"][0]["status"] == "done"
    assert ActionItem.objects.get().done_by == people["users"]["amina"]
    assert people["amina"].get(f"{ME}action-items/").json() == []
    reopened = people["secretary"].post(action, {"status": "open"}, format="json")
    assert reopened.json()["action_items"][0]["done_at"] is None


def test_a_body_invites_its_seated_representatives(club, people, admin):
    club.country, club.region = "KE", "Mombasa"
    club.save(update_fields=["country", "region"])
    body = make_body("Mombasa Region TT", make_user("regional@example.com", display_name="Regional"))
    desk = logged_in(body.memberships.get().user)
    today = timezone.localdate()
    seat = {"body": body, "sender": club, "status": Representative.Status.ACCEPTED}
    Representative.objects.create(user=people["users"]["amina"], **seat)
    Representative.objects.create(user=people["users"]["baraka"], term_end=today - timedelta(days=1), **seat)
    Representative.objects.create(
        user=people["users"]["secretary"], body=body, sender=club, status=Representative.Status.PENDING
    )
    call = {"title": "Reps", "audience": "representatives", "starts_at": soon(2), "ends_at": soon(3)}
    assert people["officer"].post(url(club), call, format="json").status_code == 400  # a club has none
    meeting = desk.post(url(body), call, format="json").json()
    out = desk.post(url(body, meeting["id"], "publish/"), format="json").json()
    assert [(i["display_name"], i["club"]) for i in out["invitees"]] == [("Amina", club.name)]
    assert people["amina"].get(url(body, meeting["id"])).status_code == 200
    assert people["baraka"].get(url(body, meeting["id"])).status_code == 404
