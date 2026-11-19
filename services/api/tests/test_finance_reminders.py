"""Dues views and reminders (REQ-023, EVAL-023; TASK-039)."""

import uuid
from datetime import date

import pytest
from django.core.management import call_command

from finance import dues
from finance.models import Campaign, Charge
from notifications.models import Notification

from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member

pytestmark = pytest.mark.django_db


def member(club, name):
    user = make_user(f"{name.lower()}@example.com", display_name=name)
    add_member(club, user)
    return user


def campaign(staff, club, **body):
    payload = {
        "title": "Club operations",
        "amount_minor": 50000,
        "cadence": "monthly",
        "starts_on": "2026-09-01",
    }
    response = staff.post(f"{ORGS}{club.id}/finance/campaigns/", {**payload, **body}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def pay(staff, club, user, the_charge, amount):
    payment = staff.post(
        f"{ORGS}{club.id}/finance/payments/",
        {
            "payer_id": str(user.id),
            "amount_minor": amount,
            "method": "cash",
            "received_on": "2026-11-01",
            "request_key": str(uuid.uuid4()),
        },
        format="json",
    ).json()
    staff.post(
        f"{ORGS}{club.id}/finance/payments/{payment['id']}/allocate/",
        {"charge_id": str(the_charge.id), "amount_minor": amount},
        format="json",
    )


def reminders(user):
    return list(Notification.objects.filter(recipient=user, category="dues").order_by("created_at"))


def test_statuses_and_totals_match_the_records_for_staff_and_member(staff, club):
    ama, bo = member(club, "Ama"), member(club, "Bo")
    made = campaign(staff, club)  # September, October and November have fallen
    september, october, november = Charge.objects.filter(member=ama).order_by("period")
    pay(staff, club, ama, september, 50000)
    pay(staff, club, ama, october, 20000)
    path = f"{ORGS}{club.id}/finance/campaigns/{made['id']}/dues/"
    roster = staff.get(path).json()
    # Ama paid September, part of October and none of November: two overdue. Bo and the admin owe all
    # three, all overdue.
    assert roster["counts"]["paid"] == 1
    assert roster["counts"]["overdue"] == 8
    owed_by_ama = 30000 + 50000
    assert roster["outstanding_minor"] == owed_by_ama + 2 * 150000
    overdue = staff.get(path, {"status": "overdue"}).json()["dues"]
    assert {d["member_name"] for d in overdue} == {"Ama", "Bo", "Club Admin"}
    assert all(d["status"] == "overdue" for d in overdue)
    mine = logged_in(ama).get(f"{ORGS}{club.id}/my-finances/").json()
    assert mine["dues"] == [
        {
            "campaign_id": made["id"],
            "title": "Club operations",
            "cadence": "monthly",
            "currency": "KES",
            "outstanding_minor": owed_by_ama,
            "overdue_minor": owed_by_ama,
            "next_due_on": dues.next_period(Campaign.objects.get(pk=made["id"]), date.today()).isoformat(),
        }
    ]
    assert all(c["member_id"] == str(ama.id) for c in mine["charges"])
    assert logged_in(bo).get(path).status_code == 403


def test_a_due_is_announced_once_on_its_day_and_once_more_when_overdue(staff, club):
    ama = member(club, "Ama")
    the_campaign = Campaign.objects.get(pk=campaign(staff, club, starts_on="2027-01-15")["id"])
    dues.generate(the_campaign, date(2027, 1, 15))
    dues.remind(club, date(2027, 1, 15))
    dues.remind(club, date(2027, 1, 15))
    assert [r.title for r in reminders(ama)] == ["Club operations: KES 500 due today"]
    dues.remind(club, date(2027, 1, 16))
    dues.remind(club, date(2027, 1, 20))
    due, overdue = reminders(ama)
    assert due.superseded and overdue.title == "Club operations: KES 500 is overdue since 15 Jan"
    # Paid dues are not chased.
    bo = member(club, "Bo")
    dues.generate(the_campaign, date(2027, 2, 15))
    pay(staff, club, ama, Charge.objects.get(member=ama, period=date(2027, 2, 15)), 50000)
    dues.remind(club, date(2027, 2, 16))
    assert len(reminders(ama)) == 2  # February's is paid
    assert reminders(bo)[-1].title.startswith("Club operations: KES 500 is overdue")


def test_staff_nudge_reaches_overdue_members_once_a_day(staff, club):
    ama = member(club, "Ama")
    made = campaign(staff, club)
    path = f"{ORGS}{club.id}/finance/campaigns/{made['id']}/remind/"
    first = staff.post(path, format="json").json()["sent"]
    assert first == 6  # three overdue dues each for Ama and the admin
    assert staff.post(path, format="json").json()["sent"] == 0
    assert logged_in(ama).post(path, format="json").status_code == 403


def test_reminders_respect_the_dues_preference_and_the_command_runs_them(staff, club):
    ama = member(club, "Ama")
    logged_in(ama).put(
        "/api/v1/me/notification-preferences/",
        {"preferences": [{"category": "dues", "enabled": False}]},
        format="json",
    )
    campaign(staff, club)
    call_command("generate_dues")
    assert reminders(ama) == []
    assert Notification.objects.filter(category="dues").exists()  # the admin still hears
