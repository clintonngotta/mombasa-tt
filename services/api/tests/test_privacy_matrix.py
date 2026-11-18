"""Public, tenant and private data boundaries (REQ-020, REQ-032; EVAL-020, EVAL-032; TASK-016).

One named world, then every route of the API is exercised against it:

- ACCESS says who each route and method is for. A route missing from it fails the first test, so a new
  endpoint can't ship without a decision about who may call it.
- Signed-out callers get nothing but the public routes.
- Staff routes of Coast Spinners refuse its plain member, the admin of another club and an outsider.
- Member routes of Coast Spinners refuse everybody who isn't an active member of it.
- Owner routes refuse everybody but the owner.
- Private values are seeded as unique markers; each viewer then reads every GET route and no marker may
  appear in anything served to a viewer who isn't allowed to see it.
"""

import importlib
import uuid

import pytest
from django.apps import apps
from django.urls import URLResolver, get_resolver, reverse
from django.utils import timezone
from rest_framework import serializers

from attachments.models import Attachment
from competitions import drawing, ties
from competitions.models import (
    DrawVersion,
    Entry,
    EntryPlayer,
    Event,
    LifecycleEntry,
    Lineup,
    Rubber,
    Tournament,
)
from facilities.models import Table, Venue
from matchlog.models import PersonalMatch
from organizations.models import (
    Invitation,
    JoinRequest,
    MemberField,
    MemberFieldValue,
    Membership,
    Organization,
    Role,
    seed_roles,
)
from organizations.permissions import RoleKey
from profiles.models import PlayerProfile
from reservations import service as reservations
from reservations.models import Hold, Reservation
from scoring.models import Scorecard, ScoreConflict, ScoreEvent

from .conftest import BrowserClient
from .helpers import image_upload, logged_in, make_user

pytestmark = pytest.mark.django_db

PUBLIC = "public"  # no login needed
SIGNED_IN = "signed-in"  # any logged-in player; serves only directory-level data
OWNER = "owner"  # the caller's own data only
MEMBER = "member"  # any active member of that organization
STAFF = "staff"  # needs a permission in that organization

ACCESS: dict[str, dict[str, str]] = {
    "auth-csrf": {"get": PUBLIC},
    "auth-signup": {"post": PUBLIC},
    "auth-verification-resend": {"post": PUBLIC},
    "auth-verification-confirm": {"post": PUBLIC},
    "auth-login": {"post": PUBLIC},
    "auth-logout": {"post": PUBLIC},
    "auth-password-reset": {"post": PUBLIC},
    "auth-password-reset-confirm": {"post": PUBLIC},
    "schema": {"get": PUBLIC},
    "attachment-content": {"get": PUBLIC},  # the signed token is the authorization
    "auth-me": {"get": OWNER},
    "attachment-link": {"get": SIGNED_IN},  # per-attachment policy, see test_attachments.py
    "personal-match-list": {"get": OWNER, "post": OWNER},
    "personal-match-labels": {"get": OWNER},
    "personal-match-stats": {"get": OWNER},
    "personal-match-detail": {"get": OWNER, "put": OWNER, "patch": OWNER, "delete": OWNER},
    "me-profile": {"get": OWNER, "patch": OWNER},
    "me-avatar": {"put": OWNER, "delete": OWNER},
    "me-goals": {"put": OWNER},
    "me-onboarding-complete": {"post": OWNER},
    "me-join-requests": {"get": OWNER},
    "me-invitation-list": {"get": OWNER},
    "me-invitation-accept": {"post": OWNER},
    "me-invitation-decline": {"post": OWNER},
    "me-membership-list": {"get": OWNER},
    "me-membership-leave": {"post": OWNER},
    "me-membership-fields": {"get": OWNER, "patch": OWNER},  # member-visible fields only
    "organization-list": {"get": SIGNED_IN, "post": SIGNED_IN},
    "organization-detail": {"get": SIGNED_IN},
    "organization-permissions": {"get": SIGNED_IN},
    "organization-join-requests": {"get": STAFF, "post": SIGNED_IN},  # anyone may ask to join
    "organization-join-request-approve": {"post": STAFF},
    "organization-join-request-reject": {"post": STAFF},
    "organization-invitations": {"get": STAFF, "post": STAFF},
    "organization-invitation-revoke": {"post": STAFF},
    "organization-roles": {"get": STAFF, "post": STAFF},
    "organization-role": {"patch": STAFF, "delete": STAFF},
    "organization-members": {"get": STAFF},
    "organization-member-roles": {"put": STAFF},
    "organization-member-remove": {"post": STAFF},
    "organization-member-fields": {"get": STAFF, "patch": STAFF},
    # Staff get every field definition here; other members get the active member-visible ones.
    "organization-member-field-list": {"get": MEMBER, "post": STAFF},
    "organization-member-field": {"patch": STAFF},
    "organization-member-field-retire": {"post": STAFF},
    "organization-member-field-restore": {"post": STAFF},
    # Venues: members see the ones in use; facility staff see and change them all.
    "organization-venues": {"get": MEMBER, "post": STAFF},
    "organization-venue": {"patch": STAFF},
    "organization-venue-tables": {"post": STAFF},
    "organization-venue-table": {"patch": STAFF},
    # Tournaments: published ones are for every signed-in player (signed-out pages come with TASK-035);
    # drafts and every change are for the host's competition staff.
    "organization-tournaments": {"get": STAFF, "post": STAFF},
    "tournament-list": {"get": SIGNED_IN},
    "tournament-detail": {"get": SIGNED_IN, "patch": STAFF, "delete": STAFF},
    "tournament-publish": {"post": STAFF},
    "tournament-start": {"post": STAFF},
    "tournament-complete": {"post": STAFF},
    "tournament-cancel": {"post": STAFF},
    "tournament-history": {"get": STAFF},
    "tournament-events": {"post": STAFF},
    "tournament-event": {"patch": STAFF, "delete": STAFF},
    "tournament-event-start": {"post": STAFF},
    "tournament-event-complete": {"post": STAFF},
    "tournament-event-cancel": {"post": STAFF},
    # Entries: accepted ones are for every signed-in player, the rest for their own players and for
    # competition staff. Anyone may enter; only an entry's own players withdraw it themselves.
    "tournament-event-entries": {"get": SIGNED_IN, "post": SIGNED_IN},
    "tournament-event-entry-accept": {"post": STAFF},
    "tournament-event-entry-waitlist": {"post": STAFF},
    "tournament-event-entry-reject": {"post": STAFF},
    "tournament-event-entry-staff-withdraw": {"post": STAFF},
    "tournament-event-entry-check-in": {"post": STAFF},
    "tournament-event-entry-undo-check-in": {"post": STAFF},
    "tournament-event-entry-withdraw": {"post": OWNER},
    "me-entries": {"get": OWNER},
    # Draws: the published draw is for every signed-in player; previews and drawing are for staff.
    "tournament-event-draw": {"get": SIGNED_IN},
    "tournament-event-standings": {"get": SIGNED_IN},
    "tournament-event-match": {"get": SIGNED_IN},  # of the published draw only
    # A team's lineup is handed in by its captain or by staff: who may, and who sees the picks, is
    # covered in tests/test_ties.py. Sending both teams back to choose again is for staff.
    "tournament-event-match-lineup": {"post": SIGNED_IN},
    "tournament-event-match-lineup-reset": {"post": STAFF},
    # Scoring: staff say who umpires; the sheet, its events and its confirmation exist only for the
    # umpire assigned to it (tests/test_umpire_scoring.py).
    "tournament-event-umpires": {"get": STAFF},
    "tournament-event-match-umpire": {"post": STAFF},
    "me-scorecards": {"get": OWNER},
    "scorecard-detail": {"get": OWNER},
    "scorecard-events": {"post": OWNER},
    "scorecard-confirm": {"post": OWNER},
    "scorecard-device": {"post": OWNER},
    # A conflict report is taken from whoever holds the sheet or held it before (test_scoring_conflicts.py).
    "scorecard-conflicts": {"post": OWNER},
    # Tables and what is on them, sending a match to a table and calling it back: competition staff.
    "tournament-tables": {"get": STAFF},
    "tournament-reservations": {"get": STAFF},
    "tournament-dispatch": {"get": STAFF},
    "tournament-dispatch-auto": {"post": STAFF},
    "tournament-dispatch-run": {"post": STAFF},
    "tournament-event-match-dispatch": {"post": STAFF},
    "tournament-event-match-recall": {"post": STAFF},
    "tournament-scoring": {"get": STAFF},
    "tournament-scoring-conflict-resolve": {"post": STAFF},
    "tournament-event-draw-preview": {"post": STAFF},
    "tournament-event-draw-publish": {"post": STAFF},
    "player-directory": {"get": SIGNED_IN},
    "player-detail": {"get": SIGNED_IN},
}

SPARE_TABLE = "00000000-0000-4000-8000-0000000000aa"  # a free table for the dispatch route

# Bodies that would succeed for someone allowed, so a refusal is about access and not about validation.
BODIES = {
    ("organization-invitations", "post"): {"email": "newcomer@example.com"},
    ("organization-roles", "post"): {"name": "Scorers", "permissions": []},
    ("organization-role", "patch"): {"name": "Renamed"},
    ("organization-member-roles", "put"): {"roles": []},
    ("personal-match-detail", "patch"): {"label": "Changed"},
    ("me-membership-fields", "patch"): {"values": {}},
    ("organization-member-fields", "patch"): {"values": {}},
    ("organization-member-field-list", "post"): {"label": "Locker", "kind": "text"},
    ("organization-member-field", "patch"): {"label": "Renamed field"},
    ("organization-venues", "post"): {"name": "Second hall", "town": "Mombasa"},
    ("organization-venue", "patch"): {"town": "Nyali"},
    ("organization-venue-tables", "post"): {"label": "Table 9"},
    ("organization-venue-table", "patch"): {"label": "Table 10"},
    ("organization-tournaments", "post"): {
        "name": "New cup",
        "starts_on": "2027-01-09",
        "ends_on": "2027-01-09",
    },
    ("tournament-detail", "patch"): {"name": "Renamed cup"},
    ("tournament-cancel", "post"): {"reason": "No hall"},
    ("tournament-events", "post"): {"name": "Doubles", "kind": "doubles", "format": "knockout"},
    ("tournament-event", "patch"): {"capacity": 8},
    ("tournament-event-cancel", "post"): {"reason": "Too few entries"},
    ("tournament-event-match-umpire", "post"): {"user_id": None},
    ("scorecard-events", "post"): {
        "assignment_id": "00000000-0000-4000-8000-000000000000",
        "events": [
            {
                "id": "00000000-0000-4000-8000-000000000001",
                "sequence": 1,
                "event": {"type": "start", "server": "a1", "a_end": "left"},
            }
        ],
    },
    ("scorecard-device", "post"): {"device_id": "00000000-0000-4000-8000-0000000000d1"},
    ("scorecard-conflicts", "post"): {
        "id": "00000000-0000-4000-8000-0000000000c1",
        "events": [
            {
                "id": "00000000-0000-4000-8000-0000000000e1",
                "sequence": 1,
                "event": {"type": "point", "side": "a"},
            }
        ],
    },
    ("tournament-event-match-dispatch", "post"): {"table_id": SPARE_TABLE},
    ("tournament-dispatch-auto", "post"): {"enabled": False},
    ("tournament-event-match-recall", "post"): {"reason": "Wrong table"},
    ("tournament-scoring-conflict-resolve", "post"): {"note": "Checked with both players"},
    ("scorecard-confirm", "post"): {"assignment_id": "00000000-0000-4000-8000-000000000000", "revision": 0},
}


def api_routes():
    """(route name, methods, url keyword names) for everything under /api/v1/."""

    def walk(patterns, prefix="", names=frozenset()):
        for pattern in patterns:
            found = names | set(pattern.pattern.regex.groupindex)  # ids may sit in an include() prefix
            if isinstance(pattern, URLResolver):
                yield from walk(pattern.url_patterns, prefix + str(pattern.pattern), found)
            elif prefix.startswith("api/v1/"):
                yield pattern, found

    for pattern, names in walk(get_resolver().url_patterns):
        view = pattern.callback
        actions = getattr(view, "actions", None)
        if actions:
            methods = set(actions)
        else:
            cls = view.view_class
            methods = {m for m in cls.http_method_names if m != "options" and hasattr(cls, m)}
        yield pattern.name, methods, names


ROUTES = list(api_routes())


class World:
    """Coast Spinners (Amina admin, Baraka and Faith members), Nyali Loop (Chiku admin), and Daudi, who
    belongs to neither and has asked to join Coast Spinners."""

    def __init__(self):
        self.amina = make_user("amina.admin@coast.example", display_name="Amina Said")
        self.baraka = make_user("baraka.member@coast.example", display_name="Baraka Otieno")
        self.faith = make_user("faith.listed@coast.example", display_name="Faith Mwende")
        self.chiku = make_user("chiku.admin@nyali.example", display_name="Chiku Nyali")
        self.daudi = make_user("daudi.outsider@else.example", display_name="Daudi Kazi")
        # Different roles and revoked access (EVAL-020): a committee member with no member or role
        # permissions, a former member, a platform operator with no club, and somebody invited.
        self.grace = make_user("grace.committee@coast.example", display_name="Grace Achieng")
        self.hamisi = make_user("hamisi.left@coast.example", display_name="Hamisi Juma")
        self.operator = make_user("operator@platform.example", display_name="Olive Operator", is_staff=True)
        self.imani = make_user("mark.invitee@else.example", display_name="Imani Invited")

        self.coast = Organization.objects.create(name="Coast Spinners", town="Mombasa")
        self.nyali = Organization.objects.create(name="Nyali Loop", town="Nyali")
        for org, admin in ((self.coast, self.amina), (self.nyali, self.chiku)):
            roles = seed_roles(org)
            Membership.objects.create(organization=org, user=admin).roles.add(roles[RoleKey.ADMIN])
        self.baraka_membership = Membership.objects.create(organization=self.coast, user=self.baraka)
        Membership.objects.create(organization=self.coast, user=self.grace).roles.add(
            self.coast.roles.get(key=RoleKey.COMMITTEE)
        )
        Membership.objects.create(organization=self.coast, user=self.hamisi, status=Membership.Status.LEFT)
        self.faith_membership = Membership.objects.create(organization=self.coast, user=self.faith)
        self.custom_role = Role.objects.create(organization=self.coast, name="Tea committee")

        # Baraka is not in the directory: nothing of his profile is for anyone else.
        PlayerProfile.objects.create(
            user=self.baraka,
            nickname="MARK-BARAKA-NICK",
            style="MARK-BARAKA-STYLE",
            bio="MARK-BARAKA-BIO",
            published_details=["style", "bio"],  # published, but only shown while listed
        )
        # Faith is listed and published her style only.
        PlayerProfile.objects.create(
            user=self.faith,
            directory_opt_in=True,
            style="MARK-FAITH-STYLE",
            bio="MARK-FAITH-BIO",
            published_details=["style"],
        )
        for user in (self.baraka, self.faith):
            response = logged_in(user).put(
                "/api/v1/me/avatar/", {"file": image_upload("PNG", (64, 64), "me.png")}, format="multipart"
            )
            assert response.status_code == 200, response.content
        self.baraka_avatar = Attachment.objects.get(owner=self.baraka)
        self.faith_avatar = Attachment.objects.get(owner=self.faith)

        self.match = PersonalMatch.objects.create(
            owner=self.baraka,
            played_on="2026-11-01",
            label="MARK-BARAKA-LABEL",
            opponent_name="MARK-BARAKA-OPPONENT",
            notes="MARK-BARAKA-NOTE",
        )
        self.invitation = Invitation.objects.create(
            organization=self.coast, email=self.imani.email, invited_by=self.amina
        )
        self.join_request = JoinRequest.objects.create(organization=self.coast, user=self.daudi)

        # Custom member fields (REQ-005): one members see, one for staff, one retired. Faith has a value
        # under each.
        def field(label, **extra):
            return MemberField.objects.create(organization=self.coast, label=label, kind="text", **extra)

        self.member_field = field("MARK-FIELD-MEMBER", visibility=MemberField.Visibility.MEMBER)
        self.staff_field = field("MARK-FIELD-STAFF", visibility=MemberField.Visibility.STAFF)
        self.retired_field = field(
            "MARK-FIELD-RETIRED", visibility=MemberField.Visibility.MEMBER, retired_at=timezone.now()
        )
        # A venue with a table in use and one switched off; a second venue switched off.
        self.venue = Venue.objects.create(organization=self.coast, name="Makadara Hall", town="Mombasa")
        self.table = Table.objects.create(venue=self.venue, label="Table 1")
        Table.objects.create(venue=self.venue, label="MARK-TABLE-OFF", position=1, active=False)
        Venue.objects.create(organization=self.coast, name="MARK-VENUE-OFF", town="Mombasa", active=False)

        # One tournament per state, so every staff action has something it would be valid on.
        def tournament(name, status, event_status=Event.Status.SCHEDULED):
            made = Tournament.objects.create(
                organization=self.coast,
                venue=self.venue,
                name=name,
                starts_on="2026-12-05",
                ends_on="2026-12-06",
                timezone="Africa/Nairobi",
                status=status,
            )
            made.event = Event.objects.create(
                tournament=made,
                name=f"{name} singles",
                kind="singles",
                format="knockout",
                status=event_status,
            )
            return made

        status = Tournament.Status
        self.draft = tournament("MARK-DRAFT-CUP", status.DRAFT)
        self.spare_draft = tournament("MARK-SPARE-DRAFT-CUP", status.DRAFT)
        self.deletable = tournament("MARK-DELETABLE-CUP", status.DRAFT)  # the staff checks delete it
        self.published = tournament("Published Cup", status.PUBLISHED)
        self.to_cancel = tournament("Doomed Cup", status.PUBLISHED)
        self.running = tournament("Running Cup", status.IN_PROGRESS)
        self.finishing = tournament("Finishing Cup", status.IN_PROGRESS, Event.Status.COMPLETED)
        self.playing = tournament("Playing Cup", status.IN_PROGRESS, Event.Status.IN_PROGRESS)
        LifecycleEntry.objects.create(
            tournament=self.published, action="published", actor=self.amina, reason="MARK-HISTORY-REASON"
        )

        # Entries in a tournament of their own, one per staff action. Baraka's are not accepted, so
        # they are for him and staff only; Faith's is accepted and open to everyone.
        self.entered = tournament("Entered Cup", status.PUBLISHED)

        def entry(user, state=Entry.Status.PENDING, **extra):
            made = Entry.objects.create(event=self.entered.event, status=state, entered_by=user, **extra)
            EntryPlayer.objects.create(entry=made, event=made.event, user=user, live=state in Entry.LIVE)
            return made

        self.baraka_entry = entry(self.baraka)
        entry(self.baraka, Entry.Status.REJECTED, reason="MARK-ENTRY-REASON")
        self.faith_entry = entry(self.faith, Entry.Status.ACCEPTED)
        self.entry_to_accept = entry(self.daudi)
        self.entry_to_waitlist = entry(self.imani)
        self.entry_to_reject = entry(self.hamisi)
        self.entry_to_withdraw = entry(self.grace, Entry.Status.ACCEPTED)
        # A preview of the draw, which only staff see: its version number is the marker.
        self.entered.event.seeding = "manual"
        self.entered.event.save()
        self.preview = drawing.make_preview(self.entered.event, self.amina, [], rng_seed=424242)
        DrawVersion.objects.filter(pk=self.preview.pk).update(version=987654321)
        self.preview_match_id = self.preview.matches.first().id

        # A team tie whose lineups are both in, for the lineup routes.
        self.team_cup = tournament("Team Cup", status.PUBLISHED)
        team_event = self.team_cup.event
        Event.objects.filter(pk=team_event.pk).update(
            kind="team", format="round_robin", tie_rubbers=["singles"], tie_wins_needed=1
        )
        team_event.refresh_from_db()
        for name in ("Tudor", "Nyali"):
            captain = make_user(f"{name.lower()}-captain@example.com")
            team = Entry.objects.create(
                event=team_event, status=Entry.Status.ACCEPTED, team_name=name, captain=captain
            )
            EntryPlayer.objects.create(entry=team, event=team_event, user=captain)
        drawing.make_preview(team_event, self.amina, [], rng_seed=1)
        self.tie = drawing.publish(team_event, self.amina).matches.get()
        for team in (self.tie.entry_a, self.tie.entry_b):
            ties.submit_lineup(self.tie, team, self.amina, [[str(team.captain_id)]])

        # A singles match under way with Baraka as its umpire, for the scoring routes.
        self.scored_cup = tournament("Scored Cup", status.IN_PROGRESS, Event.Status.IN_PROGRESS)
        for name in ("one", "two"):
            made = Entry.objects.create(event=self.scored_cup.event, status=Entry.Status.ACCEPTED)
            EntryPlayer.objects.create(
                entry=made, event=made.event, user=make_user(f"scored-{name}@example.com")
            )
        drawing.make_preview(self.scored_cup.event, self.amina, [], rng_seed=1)
        self.scored_match = drawing.publish(self.scored_cup.event, self.amina).matches.get()
        # Its umpire holds a role that only lets them score; nobody else can reach the sheet.
        self.scorer = make_user("zuri.scorer@coast.example", display_name="Zuri Scorer")
        scoring_only = Role.objects.create(
            organization=self.coast, name="Table umpires", permissions=["scoring.assigned"]
        )
        Membership.objects.create(organization=self.coast, user=self.scorer).roles.add(scoring_only)
        self.scorecard = Scorecard.objects.create(match=self.scored_match, umpire=self.scorer)

        # Two more matches under way for the dispatch routes: one to send to a table, one already on one.
        def under_way(name, players):
            cup = tournament(name, status.IN_PROGRESS, Event.Status.IN_PROGRESS)
            for label in players:
                made = Entry.objects.create(
                    event=cup.event, status=Entry.Status.ACCEPTED, checked_in_at=timezone.now()
                )
                EntryPlayer.objects.create(
                    entry=made, event=made.event, user=make_user(f"{label}@dispatch.example")
                )
            drawing.make_preview(cup.event, self.amina, [], rng_seed=1)
            return cup, drawing.publish(cup.event, self.amina).matches.get()

        self.dispatch_cup, self.to_dispatch = under_way("Dispatch Cup", ("d1", "d2"))
        self.recall_cup, self.on_table = under_way("Recall Cup", ("r1", "r2"))
        self.spare_table = Table.objects.create(id=SPARE_TABLE, venue=self.venue, label="Dispatch table")
        reservations.dispatch(
            self.on_table, Table.objects.create(venue=self.venue, label="Recall table"), self.amina
        )
        self.conflict = ScoreConflict.objects.create(
            id=uuid.uuid4(),
            scorecard=self.scorecard,
            reported_by=self.scorer,
            events=[{"id": str(uuid.uuid4()), "sequence": 1, "event": {"type": "point", "side": "a"}}],
        )

        for which, value in (
            (self.member_field, "MARK-FAITH-VALUE-MEMBER"),
            (self.staff_field, "MARK-FAITH-VALUE-STAFF"),
            (self.retired_field, "MARK-FAITH-VALUE-RETIRED"),
        ):
            MemberFieldValue.objects.create(membership=self.faith_membership, field=which, value=value)

        self.viewers = {
            "amina": self.amina,
            "baraka": self.baraka,
            "faith": self.faith,
            "chiku": self.chiku,
            "daudi": self.daudi,
            "grace": self.grace,
            "hamisi": self.hamisi,
            "operator": self.operator,
        }

    def kwargs(self, name: str, names: set[str]) -> dict:
        """Real ids of Coast Spinners or Baraka for a route, so a refusal is never just 'no such id'."""
        pk = {
            "attachment-link": self.baraka_avatar.id,
            "attachment-content": self.baraka_avatar.id,
            "personal-match-detail": self.match.id,
            "me-invitation-accept": self.invitation.id,
            "me-invitation-decline": self.invitation.id,
            "me-membership-leave": self.baraka_membership.id,
            "me-membership-fields": self.baraka_membership.id,
            # Faith's, because the staff checks remove Baraka before they reach this route.
            "organization-member-fields": self.faith_membership.id,
            "organization-member-field": self.staff_field.id,
            "organization-member-field-retire": self.staff_field.id,
            "organization-member-field-restore": self.staff_field.id,
            "organization-join-request-approve": self.join_request.id,
            "organization-join-request-reject": self.join_request.id,
            "organization-invitation-revoke": self.invitation.id,
            "organization-role": self.custom_role.id,
            "organization-member-roles": self.baraka_membership.id,
            "organization-member-remove": self.baraka_membership.id,
            "organization-venue": self.venue.id,
            "organization-venue-tables": self.venue.id,
            "organization-venue-table": self.venue.id,
            "tournament-detail": self.deletable.id,
            "tournament-publish": self.spare_draft.id,
            "tournament-start": self.published.id,
            "tournament-complete": self.finishing.id,
            "tournament-cancel": self.to_cancel.id,
            "tournament-history": self.published.id,
            "tournament-event": self.draft.event.id,
            "tournament-event-start": self.running.event.id,
            "tournament-event-complete": self.playing.event.id,
            "tournament-event-cancel": self.published.event.id,
            "tournament-event-entry-accept": self.entry_to_accept.id,
            "tournament-event-entry-waitlist": self.entry_to_waitlist.id,
            "tournament-event-entry-reject": self.entry_to_reject.id,
            "tournament-event-entry-staff-withdraw": self.entry_to_withdraw.id,
            "tournament-event-entry-check-in": self.faith_entry.id,
            "tournament-event-entry-undo-check-in": self.faith_entry.id,
            "tournament-event-entry-withdraw": self.baraka_entry.id,
            "tournament-event-match": self.preview_match_id,
            "tournament-event-match-lineup": self.tie.id,
            "tournament-event-match-lineup-reset": self.tie.id,
            "tournament-event-match-umpire": self.scored_match.id,
            "tournament-event-match-dispatch": self.to_dispatch.id,
            "tournament-event-match-recall": self.on_table.id,
            "scorecard-detail": self.scorecard.id,
            "scorecard-events": self.scorecard.id,
            "scorecard-confirm": self.scorecard.id,
            "scorecard-device": self.scorecard.id,
            "scorecard-conflicts": self.scorecard.id,
            "tournament-scoring-conflict-resolve": self.conflict.id,
            "organization-detail": self.coast.id,
            "player-detail": self.baraka.id,
        }
        found = {}
        if "organization_pk" in names:
            found["organization_pk"] = self.coast.id
        if "pk" in names:
            found["pk"] = pk[name]
        if "table_pk" in names:
            found["table_pk"] = self.table.id
        whole = ("tournament-tables", "tournament-reservations")
        if name.startswith(("tournament-scoring", "tournament-dispatch")) or name in whole:
            found["tournament_pk"] = self.scored_cup.id
            return found
        if name in ("tournament-event-match-dispatch", "tournament-event-match-recall"):
            cup = self.dispatch_cup if name.endswith("dispatch") else self.recall_cup
            found["event_pk"], found["tournament_pk"] = cup.event.id, cup.id
            return found
        if name in ("tournament-event-umpires", "tournament-event-match-umpire"):
            found["event_pk"] = self.scored_cup.event.id
            found["tournament_pk"] = self.scored_cup.id
        elif name.startswith("tournament-event-match-lineup"):
            found["event_pk"] = self.team_cup.event.id
            found["tournament_pk"] = self.team_cup.id
        elif "event_pk" in names:
            # Entries are reached through the event they are for.
            found["event_pk"] = self.entered.event.id
            found["tournament_pk"] = self.entered.id
        elif "tournament_pk" in names:
            # The event addressed by `pk` decides which tournament it is reached through.
            event = Event.objects.filter(pk=found.get("pk")).first()
            found["tournament_pk"] = event.tournament_id if event else self.draft.id
        return found

    def url(self, name: str, names: set[str]) -> str:
        return reverse(name, kwargs=self.kwargs(name, names))

    def state(self) -> dict:
        """Everything the refused requests could have changed."""
        return {
            "members": sorted(Membership.objects.values_list("user__email", "organization__name", "status")),
            "member_roles": sorted(Membership.roles.through.objects.values_list("membership_id", "role_id")),
            "roles": sorted(Role.objects.values_list("organization__name", "name", "permissions")),
            "invitations": sorted(Invitation.objects.values_list("email", "status")),
            "join_requests": sorted(JoinRequest.objects.values_list("user__email", "status")),
            "matches": sorted(PersonalMatch.objects.values_list("id", "label", "notes")),
            "avatars": sorted(PlayerProfile.objects.values_list("user__email", "avatar_id")),
            "member_fields": sorted(
                MemberField.objects.values_list("label", "visibility", "required", "retired_at")
            ),
            "member_field_values": sorted(MemberFieldValue.objects.values_list("field__label", "value")),
            "venues": sorted(Venue.objects.values_list("name", "town", "active")),
            "tables": sorted(Table.objects.values_list("label", "active")),
            "tournaments": sorted(Tournament.objects.values_list("name", "status", "cancel_reason")),
            "events": sorted(Event.objects.values_list("name", "status", "capacity", "cancel_reason")),
            "lifecycle": LifecycleEntry.objects.count(),
            "entries": sorted(Entry.objects.values_list("id", "status", "checked_in_at", "reason")),
            "entry_players": sorted(EntryPlayer.objects.values_list("entry_id", "user__email", "live")),
            "scorecards": sorted(Scorecard.objects.values_list("umpire__email", "revision", "confirmed_at")),
            "score_events": ScoreEvent.objects.count(),
            "reservations": sorted(Reservation.objects.values_list("match_id", "status")),
            "holds": Hold.objects.filter(active=True).count(),
            "score_conflicts": sorted(ScoreConflict.objects.values_list("id", "resolved_at")),
            "score_devices": sorted(Scorecard.objects.values_list("device_id", "assignment_id")),
            "lineups": Lineup.objects.count(),
            "rubbers": Rubber.objects.count(),
            "draws": sorted(DrawVersion.objects.values_list("event__name", "version", "status", "rng_seed")),
        }


@pytest.fixture
def world(db):
    return World()


def call(client, method: str, name: str, url: str):
    return getattr(client, method)(url, BODIES.get((name, method), {}), format="json")


def test_every_route_has_a_decision_about_who_may_call_it():
    actual = {(name, method) for name, methods, _ in ROUTES for method in methods}
    decided = {(name, method) for name, methods in ACCESS.items() for method in methods}
    assert actual - decided == set(), "add these routes to ACCESS (and to the checks below)"
    assert decided - actual == set(), "ACCESS lists routes that no longer exist"


def test_signed_out_callers_reach_only_public_routes(world):
    before = world.state()
    anonymous = BrowserClient()
    for name, methods, names in ROUTES:
        for method in methods:
            if ACCESS[name][method] == PUBLIC:
                continue
            response = call(anonymous, method, name, world.url(name, names))
            assert response.status_code == 401, f"{method.upper()} {name}: {response.status_code}"
    assert world.state() == before


@pytest.mark.parametrize("who", ["baraka", "faith", "chiku", "daudi", "grace", "hamisi", "operator"])
def test_staff_routes_refuse_members_other_clubs_and_outsiders(world, who):
    before = world.state()
    client = logged_in(world.viewers[who])
    for name, methods, names in ROUTES:
        for method in methods:
            if ACCESS[name][method] != STAFF:
                continue
            response = call(client, method, name, world.url(name, names))
            assert response.status_code in {403, 404}, f"{method.upper()} {name}: {response.status_code}"
    assert world.state() == before


@pytest.mark.parametrize("who", ["chiku", "daudi", "hamisi", "operator"])
def test_member_routes_refuse_everyone_outside_the_club(world, who):
    before = world.state()
    client = logged_in(world.viewers[who])
    for name, methods, names in ROUTES:
        for method in methods:
            if ACCESS[name][method] != MEMBER:
                continue
            response = call(client, method, name, world.url(name, names))
            assert response.status_code in {403, 404}, f"{method.upper()} {name}: {response.status_code}"
    assert world.state() == before


@pytest.mark.parametrize("who", ["amina", "baraka", "faith", "grace"])
def test_member_routes_serve_the_clubs_members(world, who):
    client = logged_in(world.viewers[who])
    for name, _methods, names in ROUTES:
        if ACCESS[name].get("get") == MEMBER:
            assert client.get(world.url(name, names)).status_code == 200, name


def test_staff_routes_serve_the_clubs_own_admin(world):
    """The refusals above are about who is asking, not about the ids used."""
    client = logged_in(world.amina)
    for name, _methods, names in ROUTES:
        if ACCESS[name].get("get") == STAFF:
            assert client.get(world.url(name, names)).status_code == 200, name


def test_staff_actions_succeed_for_the_clubs_own_admin(world):
    """The same calls as the refusals above, made by somebody allowed: they change things, so the bodies
    in BODIES are valid and a refusal really is about who is asking."""
    client = logged_in(world.amina)
    for name, methods, names in ROUTES:
        for method in sorted(methods, key=lambda m: m == "delete"):  # delete a role after renaming it
            if ACCESS[name][method] != STAFF or method == "get":
                continue
            response = call(client, method, name, world.url(name, names))
            # The join request was approved a moment earlier, so rejecting it is a conflict, not a refusal.
            expected = {409} if name == "organization-join-request-reject" else {200, 201, 204}
            assert response.status_code in expected, f"{method.upper()} {name}: {response.content}"


def test_owner_routes_serve_the_owner(world):
    """Positive control for the refusals below: the ids used are real and reachable by their owner."""
    baraka = logged_in(world.baraka)
    match = reverse("personal-match-detail", kwargs={"pk": world.match.id})
    assert baraka.get(match).status_code == 200
    assert baraka.patch(match, BODIES["personal-match-detail", "patch"], format="json").status_code == 200
    fields = reverse("me-membership-fields", kwargs={"pk": world.baraka_membership.id})
    assert [entry["field"]["label"] for entry in baraka.get(fields).json()] == ["MARK-FIELD-MEMBER"]
    assert baraka.patch(fields, BODIES["me-membership-fields", "patch"], format="json").status_code == 200

    scorer = logged_in(world.scorer)
    sheet = scorer.get(reverse("scorecard-detail", kwargs={"pk": world.scorecard.id}))
    assert sheet.status_code == 200 and sheet.json()["status"] == "assigned"
    listed = scorer.get("/api/v1/me/scorecards/").json()["results"]
    assert [found["id"] for found in listed] == [str(world.scorecard.id)]

    mine = baraka.get("/api/v1/me/entries/").json()["results"]
    assert {e["status"] for e in mine} == {"pending", "rejected"}
    withdraw = world.url("tournament-event-entry-withdraw", {"tournament_pk", "event_pk", "pk"})
    assert baraka.post(withdraw, {}, format="json").json()["status"] == "withdrawn"

    imani = logged_in(world.imani)
    assert [i["id"] for i in imani.get("/api/v1/me/invitations/").json()["results"]] == [
        str(world.invitation.id)
    ]
    declined = imani.post(
        reverse("me-invitation-decline", kwargs={"pk": world.invitation.id}), {}, format="json"
    )
    assert declined.status_code in {200, 204}

    left = baraka.post(
        reverse("me-membership-leave", kwargs={"pk": world.baraka_membership.id}), {}, format="json"
    )
    assert left.status_code == 204


# Owner routes without an id in the path (profile, goals, lists...) always act on the caller, so there is
# nothing of somebody else's to address; what they return is covered by the marker test below.
@pytest.mark.parametrize("who", ["amina", "faith", "chiku", "daudi", "grace", "hamisi", "operator"])
def test_owner_routes_refuse_everyone_else(world, who):
    """Baraka's match, membership and the invitee's invitation, addressed by id by somebody else."""
    before = world.state()
    client = logged_in(world.viewers[who])
    for name, methods, names in ROUTES:
        for method in methods:
            if ACCESS[name][method] != OWNER or "pk" not in names:
                continue
            response = call(client, method, name, world.url(name, names))
            assert response.status_code in {403, 404}, f"{method.upper()} {name}: {response.status_code}"
    assert world.state() == before


def everything_served_to(world, user) -> str:
    """The bodies of every GET route (with searches that would match the private markers)."""
    client = logged_in(user)
    urls = [world.url(name, names) for name, methods, names in ROUTES if "get" in methods]
    urls += [
        reverse("player-detail", kwargs={"pk": world.faith.id}),
        reverse("attachment-link", kwargs={"pk": world.faith_avatar.id}),
        reverse("organization-detail", kwargs={"pk": world.nyali.id}),
        reverse("me-membership-fields", kwargs={"pk": world.faith_membership.id}),
    ]
    urls += [
        reverse("tournament-detail", kwargs={"pk": t.id})
        for t in (world.draft, world.spare_draft, world.published)
    ]
    for term in ("MARK", "baraka", "Baraka Otieno", "Faith", "coast.example", "example", "Coast", "o"):
        urls += [
            f"/api/v1/players/?search={term}",
            f"/api/v1/organizations/?search={term}",
            f"/api/v1/tournaments/?search={term}",
        ]
    urls += [
        "/api/v1/players/?page_size=100",
        "/api/v1/organizations/?page_size=100",
        "/api/v1/tournaments/?page_size=100",
        f"/api/v1/tournaments/?organization={world.coast.id}&when=upcoming",
    ]
    served = []
    for url in urls:
        response = client.get(url)
        if hasattr(response, "streaming_content"):
            continue  # file bytes, covered in test_attachments.py
        served.append(response.content.decode())
    return "\n".join(served)


def test_private_values_reach_only_the_people_they_are_for(world):
    # marker -> the viewers allowed to receive it anywhere in the API
    allowed = {
        world.amina.email: {"amina"},
        world.baraka.email: {"baraka"},
        world.faith.email: {"faith"},
        world.chiku.email: {"chiku"},
        world.daudi.email: {"daudi"},
        world.grace.email: {"grace"},
        world.hamisi.email: {"hamisi"},
        world.operator.email: {"operator"},
        world.imani.email: {"amina"},  # staff of the inviting club (the invitee isn't a viewer here)
        "MARK-BARAKA-NICK": {"baraka"},
        "MARK-BARAKA-STYLE": {"baraka"},
        "MARK-BARAKA-BIO": {"baraka"},
        "MARK-BARAKA-LABEL": {"baraka"},
        "MARK-BARAKA-OPPONENT": {"baraka"},
        "MARK-BARAKA-NOTE": {"baraka"},
        str(world.baraka_avatar.id): {"baraka"},
        str(world.match.id): {"baraka"},
        "MARK-FAITH-BIO": {"faith"},  # unpublished
        # Controls: a listed player's published detail and picture reach every signed-in viewer, which
        # shows the crawl really reads the pages where a leak would appear.
        "MARK-FAITH-STYLE": set(world.viewers),
        str(world.faith_avatar.id): set(world.viewers),
        "Tea committee": {"amina"},  # role names are for staff
        # Custom member fields: members see the member-visible definition and their own value under it;
        # staff-only and retired definitions are for staff; a retired value is served to nobody.
        "MARK-FIELD-MEMBER": {"amina", "baraka", "faith", "grace"},
        "MARK-FIELD-STAFF": {"amina"},
        "MARK-FIELD-RETIRED": {"amina"},
        "MARK-FAITH-VALUE-MEMBER": {"amina", "faith"},
        "MARK-FAITH-VALUE-STAFF": {"amina"},
        "MARK-FAITH-VALUE-RETIRED": set(),
        # Venues and tables switched off are for facility staff; drafts and the lifecycle log are for
        # competition staff. A published tournament is for everyone (control).
        "MARK-VENUE-OFF": {"amina"},
        "MARK-TABLE-OFF": {"amina"},
        "MARK-DRAFT-CUP": {"amina"},
        "MARK-SPARE-DRAFT-CUP": {"amina"},
        "MARK-DELETABLE-CUP": {"amina"},
        "MARK-HISTORY-REASON": {"amina"},
        "Published Cup": set(world.viewers),
        # Entries: Baraka's are pending and rejected, so his name and the reason he was turned down
        # stay with him and staff. Grace's accepted entry is on show (control: she is in no directory).
        "Baraka Otieno": {"amina", "baraka"},
        "MARK-ENTRY-REASON": {"amina", "baraka"},
        "Grace Achieng": set(world.viewers),
        "987654321": {"amina"},  # the draw preview
    }
    for who, user in world.viewers.items():
        served = everything_served_to(world, user)
        for marker, viewers in allowed.items():
            if who in viewers:
                assert marker in served, f"{who} should be able to see {marker}"
            else:
                assert marker not in served, f"{marker} leaked to {who}"


def test_views_of_other_people_carry_only_allowlisted_fields(world):
    """Exact key sets: adding a field to one of these replies has to be a deliberate change here."""
    viewer = logged_in(world.daudi)
    card = viewer.get("/api/v1/players/?search=Faith").json()["results"][0]
    assert set(card) == {"id", "display_name", "nickname", "avatar", "clubs"}
    page = viewer.get(f"/api/v1/players/{world.faith.id}/").json()
    assert set(page) == set(card) | {"hand", "grip", "style", "experience", "bio"}
    assert set(viewer.get(f"/api/v1/organizations/{world.coast.id}/").json()) == {
        "id",
        "name",
        "town",
        "kind",
        "timezone",
    }
    cup = viewer.get(f"/api/v1/tournaments/{world.published.id}/").json()
    assert set(cup) == {
        "id",
        "organization",
        "venue",
        "name",
        "description",
        "starts_on",
        "ends_on",
        "timezone",
        "status",
        "published_at",
        "started_at",
        "completed_at",
        "cancelled_at",
        "cancel_reason",
        "events",
    }
    assert set(cup["organization"]) == {"id", "name", "town"}
    assert set(cup["venue"]) == {"id", "name", "town", "address"}

    staff = logged_in(world.amina)
    base = f"/api/v1/organizations/{world.coast.id}"
    member = staff.get(f"{base}/members/").json()["results"][0]
    assert set(member) == {"id", "user", "display_name", "roles", "joined_at"}
    request = staff.get(f"{base}/join-requests/").json()["results"][0]
    assert set(request) == {"id", "user", "display_name", "status", "created_at", "decided_at"}


def test_model_serializers_name_every_field_they_expose():
    """Public and tenant serializers are allowlists (REQ-020): no `__all__`, no `exclude`."""
    for config in apps.get_app_configs():
        try:
            importlib.import_module(f"{config.name}.serializers")
        except ModuleNotFoundError:
            continue

    def subclasses(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from subclasses(sub)

    ours = [
        s for s in subclasses(serializers.ModelSerializer) if not s.__module__.startswith("rest_framework")
    ]
    assert len(ours) > 5
    for serializer in ours:
        meta = serializer.Meta
        assert isinstance(meta.fields, list | tuple), f"{serializer.__name__} must list its fields"
        assert not hasattr(meta, "exclude"), f"{serializer.__name__} must not use exclude"


def test_routes_outside_the_api_serve_no_data(world):
    """Health checks say only that the service is up; the Django admin is for platform operators."""
    anonymous = BrowserClient()
    for path in ("/health/live", "/health/ready"):
        response = anonymous.get(path)
        assert response.status_code == 200
        assert len(response.content) < 100
    assert anonymous.get("/admin/").status_code == 302
    assert logged_in(world.amina).get("/admin/").status_code == 302  # a club admin is not an operator
