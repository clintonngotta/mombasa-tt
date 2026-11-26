"""Internal and external club finance (REQ-051, TASK-124): the club's own list of outside sources, income
recorded by choosing one, switching a used source off, totals by internal, external and source, and the
annual report."""

import uuid
from datetime import date, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from finance.models import ExternalIncome, ExternalSource, Payment
from organizations.models import Role

from .helpers import logged_in, make_user
from .test_roles import ORGS, add_member

pytestmark = pytest.mark.django_db


def url(club, tail=""):
    return f"{ORGS}{club.id}/finance/{tail}"


@pytest.fixture
def world(club, staff):
    treasurer, viewer, member, outsider = (
        make_user(f"{name}@example.com", display_name=name.title())
        for name in ("treasurer", "viewer", "member", "outsider")
    )
    add_member(
        club,
        treasurer,
        Role.objects.create(organization=club, name="Finance", permissions=["finances.manage"]),
    )
    add_member(
        club, viewer, Role.objects.create(organization=club, name="Auditor", permissions=["finances.view"])
    )
    add_member(club, member)
    return {
        "club": club,
        "treasurer": logged_in(treasurer),
        "viewer": logged_in(viewer),
        "member": logged_in(member),
        "outsider": logged_in(outsider),
        "users": {"member": member},
    }


def source(world, name, expect=201) -> dict:
    made = world["treasurer"].post(url(world["club"], "external-sources/"), {"name": name}, format="json")
    assert made.status_code == expect, made.json()
    return made.json()


def income(world, source_id, amount, on=None, client=None, **extra):
    body = {
        "source_id": source_id,
        "amount_minor": amount,
        "received_on": str(on or timezone.localdate()),
        "request_key": str(uuid.uuid4()),
        **extra,
    }
    return (client or world["treasurer"]).post(url(world["club"], "external-income/"), body, format="json")


def test_finance_managers_keep_the_list_of_sources(world):
    club = world["club"]
    sponsor = source(world, "Sponsor")
    assert (sponsor["name"], sponsor["active"], sponsor["used"]) == ("Sponsor", True, False)
    source(world, "County grant")
    assert source(world, "sponsor", expect=400)["fields"]["name"]  # the same name, whatever the case
    assert (
        world["treasurer"]
        .post(url(club, "external-sources/"), {"name": "x", "colour": "red"}, format="json")
        .status_code
        == 400
    )
    # The auditor reads; a member and an outsider don't, and only managers change the list.
    assert [s["name"] for s in world["viewer"].get(url(club, "external-sources/")).json()] == [
        "County grant",
        "Sponsor",
    ]
    assert (
        world["viewer"].post(url(club, "external-sources/"), {"name": "Gate"}, format="json").status_code
        == 403
    )
    for who in ("member", "outsider"):
        assert world[who].get(url(club, "external-sources/")).status_code == 403
        assert world[who].get(url(club, "external-income/")).status_code == 403
        assert world[who].get(url(club, "income-totals/")).status_code == 403
    one = url(club, f"external-sources/{sponsor['id']}/")
    assert world["treasurer"].patch(one, {"name": "County grant"}, format="json").status_code == 400
    assert (
        world["treasurer"].patch(one, {"name": "Main sponsor"}, format="json").json()["name"]
        == "Main sponsor"
    )
    assert world["viewer"].delete(one).status_code == 403
    assert world["treasurer"].delete(one).status_code == 204  # never used: it can go


def test_income_is_recorded_by_choosing_a_source_and_a_used_one_is_switched_off(world):
    club = world["club"]
    sponsor, grant = source(world, "Sponsor"), source(world, "County grant")
    made = income(world, sponsor["id"], 500000, description="Kit deal", reference="INV-7")
    assert made.status_code == 201, made.json()
    assert (made.json()["source_name"], made.json()["amount_minor"], made.json()["reversed"]) == (
        "Sponsor",
        500000,
        False,
    )
    # No free text: a source must be one of the club's, and active.
    assert income(world, str(uuid.uuid4()), 100).status_code == 400
    assert (
        world["treasurer"]
        .post(
            url(club, "external-income/"),
            {
                "source": "Sponsor",
                "amount_minor": 100,
                "received_on": str(timezone.localdate()),
                "request_key": str(uuid.uuid4()),
            },
            format="json",
        )
        .status_code
        == 400
    )
    assert income(world, sponsor["id"], 0).status_code == 400
    assert income(world, sponsor["id"], 100, on=timezone.localdate() + timedelta(days=1)).status_code == 400
    assert income(world, sponsor["id"], 100, client=world["viewer"]).status_code == 403
    # The same request sent twice records it once.
    key = str(uuid.uuid4())
    first = income(world, grant["id"], 20000, request_key=key)
    again = income(world, grant["id"], 20000, request_key=key)
    assert (first.status_code, again.status_code) == (201, 200) and first.json()["id"] == again.json()["id"]
    assert ExternalIncome.objects.count() == 2

    # A used source can't be deleted: it is switched off, keeps its records and takes no new income.
    one = url(club, f"external-sources/{sponsor['id']}/")
    refused = world["treasurer"].delete(one)
    assert refused.status_code == 409 and refused.json()["code"] == "source_used"
    off = world["treasurer"].patch(one, {"active": False}, format="json").json()
    assert (off["active"], off["used"]) == (False, True)
    assert income(world, sponsor["id"], 100).status_code == 400
    assert ExternalSource.objects.filter(pk=sponsor["id"]).exists()
    listed = world["viewer"].get(url(club, "external-income/") + f"?source={sponsor['id']}").json()
    assert [(row["source_name"], row["description"]) for row in listed] == [("Sponsor", "Kit deal")]
    assert world["viewer"].get(url(club, "external-income/") + "?source=nope").status_code == 400


def test_totals_split_internal_and_external_and_by_source(world):
    club, today = world["club"], timezone.localdate()
    sponsor, grant = source(world, "Sponsor"), source(world, "County grant")
    income(world, sponsor["id"], 500000, on=today - timedelta(days=10))
    income(world, sponsor["id"], 100000, on=today - timedelta(days=5))
    income(world, grant["id"], 20000, on=today - timedelta(days=5))
    wrong = income(world, grant["id"], 77700, on=today - timedelta(days=5)).json()
    old = income(world, grant["id"], 30000, on=today - timedelta(days=60))
    assert old.status_code == 201
    for amount, days, reversed_at in ((40000, 5, None), (15000, 60, None), (99900, 5, timezone.now())):
        Payment.objects.create(
            organization=club,
            payer=world["users"]["member"],
            amount_minor=amount,
            method="cash",
            received_on=today - timedelta(days=days),
            request_key=uuid.uuid4(),
            reversed_at=reversed_at,
        )
    # Reversing keeps the record and takes it out of every total.
    reverse = url(club, f"external-income/{wrong['id']}/reverse/")
    assert world["viewer"].post(reverse, {"reason": "x"}, format="json").status_code == 403
    assert world["treasurer"].post(reverse, {}, format="json").status_code == 400
    assert (
        world["treasurer"].post(reverse, {"reason": "Entered twice"}, format="json").json()["reversed"]
        is True
    )
    assert (
        world["treasurer"].post(reverse, {"reason": "Again"}, format="json").json()["code"]
        == "already_reversed"
    )

    window = f"?from={today - timedelta(days=30)}&to={today}"
    kes = world["viewer"].get(url(club, "income-totals/") + window).json()[0]
    assert (kes["internal_minor"], kes["external_minor"], kes["total_minor"]) == (40000, 620000, 660000)
    assert [(r["source_name"], r["amount_minor"]) for r in kes["by_source"]] == [
        ("County grant", 20000),
        ("Sponsor", 600000),
    ]
    # The totals are the ledger's, added up directly.
    standing = ExternalIncome.objects.filter(
        organization=club, reversed_at__isnull=True, received_on__gte=today - timedelta(days=30)
    )
    assert kes["external_minor"] == sum(row.amount_minor for row in standing)
    everything = world["viewer"].get(url(club, "income-totals/")).json()[0]
    assert (everything["internal_minor"], everything["external_minor"]) == (55000, 650000)
    assert world["viewer"].get(url(club, "income-totals/") + "?from=yesterday").status_code == 400
    listed = world["viewer"].get(url(club, "external-income/") + window).json()
    assert len(listed) == 4 and sum(not row["reversed"] for row in listed) == 3


def test_the_annual_report_shows_external_income_by_source(world):
    from finance import reports

    club = world["club"]
    year = timezone.localdate().year - 1
    sponsor = ExternalSource.objects.create(organization=club, name="Sponsor")
    for amount, on, gone in (
        (500000, date(year, 3, 1), None),
        (30000, date(year - 1, 12, 1), None),
        (11100, date(year, 4, 1), timezone.now()),
    ):
        ExternalIncome.objects.create(
            organization=club,
            source=sponsor,
            amount_minor=amount,
            received_on=on,
            request_key=uuid.uuid4(),
            reversed_at=gone,
        )
    Payment.objects.create(
        organization=club,
        payer=world["users"]["member"],
        amount_minor=40000,
        method="cash",
        received_on=date(year, 5, 1),
        request_key=uuid.uuid4(),
    )
    kes = reports.figures(club, date(year, 1, 1), date(year, 12, 31))["currencies"][0]
    assert kes["opening_minor"] == 30000  # last year's outside money is in the opening balance
    assert (kes["internal_receipts_minor"], kes["external_receipts_minor"], kes["receipts_minor"]) == (
        40000,
        500000,
        540000,
    )
    assert {"label": "External: Sponsor", "amount_minor": 500000} in kes["receipts"]
    assert kes["closing_minor"] == 30000 + 540000
    made = world["treasurer"].post(f"{ORGS}{club.id}/annual-reports/", {}, format="json").json()
    text = world["treasurer"].get(f"{ORGS}{club.id}/annual-reports/{made['id']}/export.csv").content.decode()
    assert 'External: Sponsor,"5,000.00"' in text and 'of which from outside (external),"5,000.00"' in text


def test_listing_sources_costs_the_same_queries_for_two_or_twenty(world):
    club = world["club"]

    def queries() -> int:
        with CaptureQueriesContext(connection) as captured:
            assert world["viewer"].get(url(club, "external-sources/")).status_code == 200
        return len(captured)

    for name in ("A", "B"):
        source(world, name)
    few = queries()
    for n in range(18):
        ExternalSource.objects.create(organization=club, name=f"Source {n}")
    assert queries() == few
