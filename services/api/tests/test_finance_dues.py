"""Contribution campaigns and generated dues (REQ-023, EVAL-023; TASK-038)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command

from finance import dues
from finance.models import Campaign, Charge
from organizations.models import Membership

from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member

pytestmark = pytest.mark.django_db
NAIROBI = ZoneInfo("Africa/Nairobi")


def base(club, tail=""):
    return f"{ORGS}{club.id}/finance/{tail}"


def member(club, name):
    user = make_user(f"{name.lower()}@example.com", display_name=name)
    add_member(club, user)
    return user


def campaign(staff, club, expect=201, **body):
    payload = {
        "title": "Club operations",
        "amount_minor": 50000,
        "cadence": "monthly",
        "starts_on": "2027-01-31",
    }
    response = staff.post(base(club, "campaigns/"), {**payload, **body}, format="json")
    assert response.status_code == expect, response.json()
    return response.json()


def run(the_campaign, today):
    return dues.generate(Campaign.objects.get(pk=the_campaign["id"]), today)


def periods_of(user, the_campaign):
    return [
        (c.period.isoformat(), c.amount_minor)
        for c in Charge.objects.filter(member=user, campaign_id=the_campaign["id"]).order_by("period")
    ]


def test_monthly_dues_clamp_to_the_month_end_and_running_twice_makes_one_each(staff, club):
    ama = member(club, "Ama")
    made = campaign(staff, club)
    assert made["dues_count"] == 0  # the first period is still to come
    run(made, date(2027, 3, 31))
    assert run(made, date(2027, 3, 31)) == 0
    assert periods_of(ama, made) == [("2027-01-31", 50000), ("2027-02-28", 50000), ("2027-03-31", 50000)]
    # A leap February clamps to the 29th.
    leap = campaign(staff, club, title="Leap", starts_on="2028-01-31")
    run(leap, date(2028, 3, 1))
    assert [p for p, _ in periods_of(ama, leap)] == ["2028-01-31", "2028-02-29"]


@pytest.mark.parametrize(
    ("cadence", "starts", "until", "expected"),
    [
        ("weekly", "2027-01-04", date(2027, 1, 25), ["2027-01-04", "2027-01-11", "2027-01-18", "2027-01-25"]),
        ("quarterly", "2027-11-30", date(2028, 6, 1), ["2027-11-30", "2028-02-29", "2028-05-30"]),
        (
            "yearly",
            "2028-02-29",
            date(2032, 3, 1),
            ["2028-02-29", "2029-02-28", "2030-02-28", "2031-02-28", "2032-02-29"],
        ),
        ("once", "2027-05-01", date(2030, 1, 1), ["2027-05-01"]),
    ],
)
def test_each_cadence_falls_on_the_right_days(staff, club, cadence, starts, until, expected):
    ama = member(club, "Ama")
    made = campaign(staff, club, cadence=cadence, starts_on=starts)
    run(made, until)
    run(made, until)
    assert [p for p, _ in periods_of(ama, made)] == expected


def test_an_amount_change_affects_only_later_periods_and_terms_are_honoured(staff, club):
    ama, junior, honorary = member(club, "Ama"), member(club, "Junior"), member(club, "Honorary")
    made = campaign(staff, club, starts_on="2027-01-01")
    run(made, date(2027, 1, 15))
    path = base(club, f"campaigns/{made['id']}/")
    staff.post(f"{path}terms/", {"member_id": str(junior.id), "amount_minor": 20000}, format="json")
    refused = staff.post(f"{path}terms/", {"member_id": str(honorary.id), "waived": True}, format="json")
    assert refused.status_code == 400
    staff.post(
        f"{path}terms/",
        {"member_id": str(honorary.id), "waived": True, "waive_reason": "Honorary member"},
        format="json",
    )
    staff.patch(path, {"amount_minor": 60000}, format="json")
    run(made, date(2027, 2, 15))
    assert periods_of(ama, made) == [("2027-01-01", 50000), ("2027-02-01", 60000)]
    assert periods_of(junior, made) == [("2027-01-01", 50000), ("2027-02-01", 20000)]
    assert periods_of(honorary, made) == [("2027-01-01", 50000)]  # earlier dues stay
    terms = {t["member_name"]: t for t in staff.get(path).json()["terms"]}
    assert terms["Honorary"]["waive_reason"] == "Honorary member"


def test_new_members_owe_from_the_next_period_and_leavers_stop(staff, club):
    ama, leaver = member(club, "Ama"), member(club, "Leaver")
    made = campaign(staff, club, starts_on="2027-01-01")
    run(made, date(2027, 1, 20))
    newcomer = member(club, "Newcomer")
    Membership.objects.filter(user=newcomer).update(joined_at=datetime(2027, 1, 20, 9, tzinfo=NAIROBI))
    Membership.objects.filter(user=leaver).update(status=Membership.Status.LEFT)
    run(made, date(2027, 3, 5))
    assert [p for p, _ in periods_of(newcomer, made)] == ["2027-02-01", "2027-03-01"]
    assert [p for p, _ in periods_of(leaver, made)] == ["2027-01-01"]
    assert len(periods_of(ama, made)) == 3


def test_selected_members_only_and_a_waived_due_and_partly_paid_overdue(staff, club):
    ama, bo = member(club, "Ama"), member(club, "Bo")
    refused = campaign(staff, club, expect=400, audience="selected")
    assert refused["code"] == "members_required"
    made = campaign(
        staff,
        club,
        title="Kit",
        cadence="once",
        starts_on="2026-10-10",
        audience="selected",
        member_ids=[str(ama.id)],
    )
    run(made, date(2027, 2, 1))
    assert periods_of(bo, made) == []
    due = Charge.objects.get(member=ama, campaign_id=made["id"])
    payment = staff.post(
        base(club, "payments/"),
        {
            "payer_id": str(ama.id),
            "amount_minor": 20000,
            "method": "cash",
            "received_on": "2026-10-12",
            "request_key": "6d0f3f1e-8f0b-4c55-9d43-6f0e8b5f3c11",
        },
        format="json",
    ).json()
    staff.post(
        base(club, f"payments/{payment['id']}/allocate/"),
        {"charge_id": str(due.id), "amount_minor": 20000},
        format="json",
    )
    mine = logged_in(ama).get(f"{ORGS}{club.id}/my-finances/").json()["charges"]
    kit = next(c for c in mine if c["campaign_id"] == made["id"])
    assert (kit["status"], kit["outstanding_minor"]) == ("overdue", 30000)  # partly paid, still overdue
    waived = staff.post(base(club, f"charges/{due.id}/waive/"), {"reason": "Hardship"}, format="json").json()
    assert waived["status"] == "waived"


def test_closing_stops_new_dues_and_the_command_catches_up_once(staff, club):
    ama = member(club, "Ama")
    made = campaign(staff, club, starts_on="2026-09-01")
    call_command("generate_dues")
    call_command("generate_dues")
    already = len(periods_of(ama, made))
    assert already >= 3  # September to today
    staff.post(base(club, f"campaigns/{made['id']}/close/"), format="json")
    assert run(made, date(2030, 1, 1)) == 0
    assert len(periods_of(ama, made)) == already
    assert (
        staff.patch(base(club, f"campaigns/{made['id']}/"), {"title": "x"}, format="json").status_code == 409
    )


def test_only_finance_managers_set_up_campaigns(staff, club):
    ama = member(club, "Ama")
    assert logged_in(ama).post(base(club, "campaigns/"), {}, format="json").status_code == 403
    assert logged_in(ama).get(base(club, "campaigns/")).status_code == 403
