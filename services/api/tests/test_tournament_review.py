"""A tournament's review (REQ-055, TASK-130): written by the host's competition staff once it is over,
read by them and by the officials of its region and country, and by nobody else."""

from datetime import timedelta

import pytest
from django.utils import timezone

from competitions.models import Tournament, TournamentReview

from .helpers import logged_in, make_official, make_user
from .test_roles import add_member
from .test_tournaments import make_tournament

pytestmark = pytest.mark.django_db

REVIEW = {
    "went_well": "Matches ran to time.",
    "went_wrong": "Too few umpires on day two.",
    "actions": [
        {"text": "Recruit four more umpires", "owner": "Organizing secretary", "due_on": "2027-03-01"}
    ],
}


def url(tournament):
    return f"/api/v1/tournaments/{tournament['id']}/review/"


@pytest.fixture
def coast(club):
    club.country, club.region = "KE", "Mombasa"
    club.save(update_fields=["country", "region"])
    return club


def held(staff, club, **extra) -> dict:
    """A published tournament that ended yesterday."""
    made = make_tournament(staff, club, **extra)
    yesterday = timezone.localdate() - timedelta(days=1)
    Tournament.objects.filter(pk=made["id"]).update(
        status=Tournament.Status.PUBLISHED, starts_on=yesterday - timedelta(days=1), ends_on=yesterday
    )
    return made


def test_staff_write_the_review_once_the_tournament_is_over(coast, staff):
    upcoming = make_tournament(staff, coast)
    Tournament.objects.filter(pk=upcoming["id"]).update(
        status=Tournament.Status.PUBLISHED,
        starts_on=timezone.localdate() + timedelta(days=3),
        ends_on=timezone.localdate() + timedelta(days=4),
    )
    assert staff.get(url(upcoming)).json()["can_edit"] is False
    assert staff.put(url(upcoming), REVIEW, format="json").json()["code"] == "tournament_not_over"

    tournament = held(staff, coast)
    empty = staff.get(url(tournament)).json()
    assert (empty["went_well"], empty["actions"], empty["updated_at"], empty["can_edit"]) == (
        "",
        [],
        None,
        True,
    )
    saved = staff.put(url(tournament), REVIEW, format="json")
    assert saved.status_code == 200, saved.json()
    assert saved.json()["actions"] == [
        {
            "text": "Recruit four more umpires",
            "owner": "Organizing secretary",
            "due_on": "2027-03-01",
            "done": False,
        }
    ]
    assert saved.json()["updated_by_name"] and saved.json()["updated_at"]

    # Saving again replaces it: one review per tournament.
    done = {**REVIEW, "actions": [{**REVIEW["actions"][0], "done": True}]}
    assert staff.put(url(tournament), done, format="json").json()["actions"][0]["done"] is True
    assert TournamentReview.objects.count() == 1


def test_a_review_is_validated(coast, staff):
    tournament = held(staff, coast)
    assert staff.put(url(tournament), {}, format="json").status_code == 400
    assert staff.put(url(tournament), {**REVIEW, "rating": 5}, format="json").status_code == 400
    too_long = {**REVIEW, "went_well": "x" * 5001}
    assert staff.put(url(tournament), too_long, format="json").status_code == 400
    too_many = {"actions": [{"text": f"Action {n}"} for n in range(31)]}
    assert staff.put(url(tournament), too_many, format="json").status_code == 400
    assert TournamentReview.objects.count() == 0


def test_only_the_hosts_staff_and_its_officials_read_it(coast, staff):
    tournament = held(staff, coast)
    staff.put(url(tournament), REVIEW, format="json")
    member = make_user("member@example.com")
    add_member(coast, member)
    official, elsewhere, outsider = (
        make_user(f"{n}@example.com") for n in ("official", "kilifi", "outsider")
    )
    make_official(official, "KE", "Mombasa")
    make_official(elsewhere, "KE", "Kilifi")

    seen = logged_in(official).get(url(tournament))
    assert seen.status_code == 200 and seen.json()["went_wrong"] == "Too few umpires on day two."
    assert seen.json()["can_edit"] is False
    # An official reads; only the host's staff write.
    assert logged_in(official).put(url(tournament), REVIEW, format="json").status_code == 403
    for other in (member, elsewhere, outsider):
        client = logged_in(other)
        assert client.get(url(tournament)).status_code == 403
        assert client.put(url(tournament), REVIEW, format="json").status_code == 403
    # A draft tournament isn't there at all for them.
    draft = make_tournament(staff, coast, name="Draft Cup")
    assert logged_in(member).get(url(draft)).status_code == 404
    assert TournamentReview.objects.get().went_well == "Matches ran to time."
