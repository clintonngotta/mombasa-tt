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
from datetime import UTC, datetime, timedelta

import pytest
from django.apps import apps
from django.urls import URLResolver, get_resolver, reverse
from django.utils import timezone
from rest_framework import serializers

from accounts.models import User
from activities.models import Activity, Rsvp
from attachments.models import Attachment
from coaching.models import Availability, Booking, Coaching, CoachProfile, MatchComment
from competitions import drawing, ties
from competitions.models import (
    Announcement,
    Award,
    Ceremony,
    DrawVersion,
    Entry,
    EntryPlayer,
    Event,
    LifecycleEntry,
    Lineup,
    LiveStream,
    LiveStreamReport,
    Match,
    OfficialResult,
    Resolution,
    Rubber,
    ScheduleSession,
    ScheduleVersion,
    Tournament,
    TournamentDocument,
    TournamentReview,
)
from events.models import ExternalEvent, LinkReport
from facilities.models import Booking as TableBooking
from facilities.models import OpeningHour, Pass, Table, Venue, Visit
from feedback import service as feedback
from feedback.models import FeedbackForm, FeedbackRecipient, FeedbackResponse
from finance import welfare
from finance.models import (
    Allocation,
    AnnualReport,
    Campaign,
    CampaignMember,
    Charge,
    Expense,
    ExternalIncome,
    ExternalSource,
    FinanceSettings,
    Payment,
    WelfareContribution,
    WelfareProject,
)
from guests import service as guests
from guests.models import GuestClaim, GuestInvitation
from matchlog.models import MatchNote, PersonalMatch
from notifications.models import Notification, Preference, PushSubscription
from organizations.models import (
    AdminHandover,
    CommitteeField,
    CommitteeFieldValue,
    CommitteePosition,
    Invitation,
    JoinRequest,
    MemberField,
    MemberFieldValue,
    Membership,
    Organization,
    PositionHolder,
    Representative,
    Role,
    seed_roles,
)
from organizations.permissions import RoleKey
from outbox.models import Job
from penalties.models import AbsencePenalty, AbsenceRule
from profiles.models import PlayerProfile
from regions.models import (
    ActionItem,
    AgendaItem,
    Article,
    Meeting,
    MeetingDocument,
    MeetingInvitee,
    MeetingPenalty,
    MinutesAmendment,
    Sponsorship,
)
from reservations import service as reservations
from reservations.models import Hold, Reservation, TournamentUmpire
from scoring.models import Scorecard, ScoreConflict, ScoreEvent
from soda.models import Challenge, Policy
from squads.models import Squad, SquadPlace
from training.models import (
    ClubSession,
    Drill,
    Equipment,
    PlanItem,
    SessionInvitation,
    TrainingPlan,
    TrainingRules,
)

from .conftest import BrowserClient
from .helpers import image_upload, logged_in, make_user

pytestmark = pytest.mark.django_db

PUBLIC = "public"  # no login needed
SIGNED_IN = "signed-in"  # any logged-in player; serves only directory-level data
OWNER = "owner"  # the caller's own data only
MEMBER = "member"  # any active member of that organization
STAFF = "staff"  # needs a permission in that organization
APPROVER = "approver"  # a platform super admin or the scoped official for the competition

ACCESS: dict[str, dict[str, str]] = {
    "auth-csrf": {"get": PUBLIC},
    "auth-signup": {"post": PUBLIC},
    "auth-verification-resend": {"post": PUBLIC},
    "auth-verification-confirm": {"post": PUBLIC},
    "auth-login": {"post": PUBLIC},
    "auth-logout": {"post": PUBLIC},
    "auth-password-reset": {"post": PUBLIC},
    "auth-password-reset-confirm": {"post": PUBLIC},
    # The invitation link's secret is the authorization; joining creates the invitee's account.
    "auth-invitation": {"get": PUBLIC, "post": PUBLIC},
    "auth-invitation-claim": {"post": OWNER},
    "schema": {"get": SIGNED_IN},
    "geography-countries": {"get": PUBLIC},
    # The events listing (REQ-042) is public; pending external events reach the submitting club only.
    "events": {"get": PUBLIC},
    "external-event-review": {"get": APPROVER},  # platform curators, see test_events_listing.py
    "external-event-approve": {"post": APPROVER},
    "external-event-reject": {"post": APPROVER},
    "external-event-remove-link": {"post": APPROVER},
    "external-event-report": {"post": SIGNED_IN},
    "organization-external-events": {"get": STAFF, "post": STAFF},
    "organization-external-event": {"patch": STAFF},
    "organization-external-event-live": {"post": STAFF},
    "geography-country": {"get": PUBLIC},
    "attachment-content": {"get": PUBLIC},  # the signed token is the authorization
    "auth-me": {"get": OWNER, "patch": OWNER},
    "auth-me-email": {"post": OWNER},  # a phone-only account asks to add an email: a link is sent
    "attachment-link": {"get": SIGNED_IN},  # per-attachment policy, see test_attachments.py
    "personal-match-list": {"get": OWNER, "post": OWNER},
    "personal-match-labels": {"get": OWNER},
    "personal-match-stats": {"get": OWNER},
    "personal-match-detail": {"get": OWNER, "put": OWNER, "patch": OWNER, "delete": OWNER},
    "match-note-list": {"get": OWNER, "post": OWNER},
    "match-note-detail": {"get": OWNER, "patch": OWNER, "delete": OWNER},
    "me-profile": {"get": OWNER, "patch": OWNER},
    "me-avatar": {"put": OWNER, "delete": OWNER},
    "me-goals": {"put": OWNER},
    "me-onboarding-complete": {"post": OWNER},
    "me-join-requests": {"get": OWNER},
    "me-invitation-list": {"get": OWNER},
    "me-invitation-accept": {"post": OWNER},
    "me-invitation-decline": {"post": OWNER},
    "me-guest-invitation-list": {"get": OWNER},
    "me-guest-invitation-accept": {"post": OWNER},
    "me-guest-invitation-decline": {"post": OWNER},
    "me-guest-claim-list": {"get": OWNER},
    "me-membership-list": {"get": OWNER},
    "me-managed-organizations": {"get": OWNER},
    "me-membership-leave": {"post": OWNER},
    "me-membership-fields": {"get": OWNER, "patch": OWNER},  # member-visible fields only
    # Training (REQ-026, REQ-027): equipment, personal drills and plans are the player's own.
    "my-equipment": {"get": OWNER, "put": OWNER},
    "my-training-sessions": {"get": OWNER},
    "my-facility-visit-list": {"get": OWNER},
    # Table bookings (REQ-021): the requester's own; the venue's facility staff decide.
    "my-table-booking-list": {"get": OWNER, "post": OWNER},
    "my-table-booking-cancel": {"post": OWNER},
    "organization-bookings": {"get": STAFF},
    "organization-booking-approve": {"post": STAFF},
    "organization-booking-reject": {"post": STAFF},
    "organization-booking-cancel": {"post": STAFF},
    # Soda games (REQ-040): the two players' own; a club sees only what both shared.
    "my-soda-settings": {"get": OWNER},
    # The notification inbox (REQ-019): the player's own alerts and preferences.
    "notification-list": {"get": OWNER},
    "notification-unread-count": {"get": OWNER},
    "notification-read": {"post": OWNER},
    "notification-read-all": {"post": OWNER},
    "my-notification-preferences": {"get": OWNER, "put": OWNER},
    # Browser push (TASK-034): the player's own devices.
    "my-push": {"get": OWNER},
    "my-push-subscribe": {"post": OWNER},
    "my-push-unsubscribe": {"post": OWNER},
    "my-push-device": {"delete": OWNER},
    "organization-announcements": {"post": STAFF},
    # The manual ledger (REQ-022): finance staff record and read; a member reads their own.
    "organization-charges": {"get": STAFF, "post": STAFF},
    "organization-charge-waive": {"post": STAFF},
    "organization-payments": {"get": STAFF, "post": STAFF},
    "organization-payment-allocate": {"post": STAFF},
    "organization-payment-reverse": {"post": STAFF},
    "organization-balances": {"get": STAFF},
    "organization-campaigns": {"get": STAFF, "post": STAFF},
    "organization-campaign": {"get": STAFF, "patch": STAFF},
    "organization-campaign-close": {"post": STAFF},
    "organization-campaign-terms": {"post": STAFF},
    "organization-campaign-dues": {"get": STAFF},
    "organization-campaign-remind": {"post": STAFF},
    "organization-expenses": {"get": STAFF, "post": STAFF},
    "organization-expense-reverse": {"post": STAFF},
    "organization-expense-receipt": {"put": STAFF},
    "organization-finance-summary": {"get": STAFF},
    "organization-finance-purposes": {"get": MEMBER},
    # REQ-038 welfare: the audience sees totals and its own gift; welfare and finance staff run it.
    "organization-welfare-projects": {"get": MEMBER, "post": STAFF},
    "organization-welfare-project": {"get": MEMBER, "patch": STAFF},
    "organization-welfare-project-hide": {"post": STAFF},
    "organization-welfare-project-close": {"post": STAFF},
    "organization-welfare-project-due": {"post": STAFF},
    "organization-welfare-contributions": {"get": STAFF, "post": STAFF},
    "organization-welfare-contribution-reverse": {"post": STAFF},
    "organization-welfare-expenses": {"get": STAFF, "post": STAFF},
    "organization-my-finances": {"get": MEMBER},
    "soda-game-list": {"get": OWNER, "post": OWNER},
    "soda-game-detail": {"get": OWNER},
    "soda-game-accept": {"post": OWNER},
    "soda-game-counter": {"post": OWNER},
    "soda-game-decline": {"post": OWNER},
    "soda-game-withdraw": {"post": OWNER},
    "soda-game-result": {"post": OWNER},
    "soda-game-confirm": {"post": OWNER},
    "soda-game-dispute": {"post": OWNER},
    "soda-game-settle": {"post": OWNER},
    "soda-game-share": {"post": OWNER},
    "organization-soda-games": {"get": MEMBER},
    "organization-soda-policy": {"get": MEMBER, "put": STAFF},
    # Club sessions (REQ-027): a member answers their own invitations; training staff run the rest.
    "my-session-invitation-list": {"get": OWNER},
    "my-session-invitation-accept": {"post": OWNER},
    "my-session-invitation-check-in": {"post": OWNER},  # Baraka's invitation, from Baraka's phone
    "my-session-invitation-apologise": {"post": OWNER},
    "my-session-invitation-decline": {"post": OWNER},
    "my-drill-list": {"get": OWNER, "post": OWNER},
    "my-drill-detail": {"get": OWNER, "put": OWNER, "patch": OWNER, "delete": OWNER},
    "training-plan-list": {"get": OWNER, "post": OWNER},
    "training-plan-detail": {"get": OWNER, "put": OWNER, "patch": OWNER, "delete": OWNER},
    "training-plan-recommendations": {"get": OWNER},
    "training-plan-items": {"post": OWNER},  # someone else's plan id is a 404, see test_training
    "training-plan-item": {"patch": OWNER, "delete": OWNER},
    # A club's drills: members read them, training staff change them.
    # Award ceremonies (REQ-049): a draft ceremony is for the host's competition staff alone.
    # Published tournaments are public (TASK-035): a draft ceremony is still the staff's (test_public_views).
    "tournament-ceremony": {"get": PUBLIC, "put": STAFF},
    # The review of a finished tournament: its host's competition staff (and the region's officials).
    "tournament-review": {"get": STAFF, "put": STAFF},
    # Results announcements (TASK-085): the feed of a published tournament is public; drafts and every
    # change are the host's competition staff's. The detail route is exercised on a draft (see kwargs),
    # which is "not found" for everyone else: its text is checked with the private markers below.
    "tournament-announcements": {"get": PUBLIC, "post": STAFF},
    "tournament-announcement": {"get": PUBLIC, "patch": STAFF, "delete": STAFF},
    "tournament-announcement-publish": {"post": STAFF},
    "tournament-announcement-amend": {"post": STAFF},
    "tournament-announcement-card": {"get": PUBLIC},
    # The same published text as a PDF: one post, or the tournament's whole sheet (never drafts).
    "tournament-announcement-pdf": {"get": PUBLIC},
    "tournament-announcements-pdf": {"get": PUBLIC},
    "tournament-live": {"get": PUBLIC},
    "tournament-ceremony-generate": {"post": STAFF},
    "tournament-ceremony-publish": {"post": STAFF},
    "tournament-ceremony-reorder": {"post": STAFF},
    "tournament-ceremony-awards": {"post": STAFF},
    "tournament-ceremony-award": {"patch": STAFF, "delete": STAFF},
    "tournament-ceremony-award-present": {"post": STAFF},
    "me-honours": {"get": OWNER},
    # Regional bodies (REQ-048). Coast Spinners is in the Mombasa region of "Coast Region TT", whose
    # admin is Amina: the region's clubs read the agenda and published articles; body staff write them.
    # Creating a body is for platform super admins only (TASK-107), see test_governing_bodies.
    "regional-bodies": {"get": SIGNED_IN, "post": APPROVER},
    "organization-region-clubs": {"get": STAFF},
    "organization-agenda": {"get": MEMBER, "post": STAFF},
    "organization-agenda-item": {"patch": STAFF, "delete": STAFF},
    "organization-articles": {"get": MEMBER, "post": STAFF},
    "organization-article": {"get": MEMBER, "patch": STAFF, "delete": STAFF},
    "organization-article-publish": {"post": STAFF},
    "my-agenda": {"get": OWNER},
    "my-articles": {"get": OWNER},
    "my-meetings": {"get": OWNER},
    # Coast's meetings: governance staff run them, invitees answer and check in. The list answers
    # everyone with what is theirs to see.
    "organization-meetings": {"get": SIGNED_IN, "post": STAFF},
    "organization-meeting": {"get": STAFF, "patch": STAFF, "delete": STAFF},  # a draft
    "organization-meeting-publish": {"post": STAFF},
    "organization-meeting-cancel": {"post": STAFF},
    "organization-meeting-minutes": {"post": STAFF},
    # Approving and amending minutes, and a meeting's documents: governance staff. An action item's
    # status: staff or its owner (Amina's here, so Baraka, who reads the minutes, is refused).
    "organization-meeting-minutes-approve": {"post": STAFF},
    "organization-meeting-minutes-amendments": {"post": STAFF},
    "organization-meeting-action-item": {"post": STAFF},
    "organization-meeting-documents": {"post": STAFF},
    "organization-meeting-document": {"delete": STAFF},
    "my-action-items": {"get": OWNER},
    "organization-meeting-answer": {"post": OWNER},  # Baraka's invitation
    "organization-meeting-check-in": {"post": OWNER},
    # Attendance and issuing: governance staff (or the meeting's secretary, nobody here). Changing an
    # issued penalty: the club admin only, which the staff check covers.
    "organization-meeting-attendance": {"post": STAFF},
    "organization-meeting-penalties": {"post": STAFF},
    "organization-meeting-penalty": {"patch": STAFF},
    # Sponsorships: Coast's finance staff offer; a host's competition staff decide; sponsors are shown.
    "organization-sponsorships": {"get": STAFF, "post": STAFF},
    "organization-sponsorship-withdraw": {"post": STAFF},
    "tournament-sponsors": {"get": PUBLIC},
    # Watch links (REQ-042): seen and reported by everyone who sees the tournament; staff manage them.
    "tournament-streams": {"get": PUBLIC, "post": STAFF},
    "tournament-stream": {"patch": STAFF, "delete": STAFF},
    # A tournament's cover and documents (REQ-007): shown with it; its host's competition staff change them.
    "tournament-cover": {"put": STAFF, "delete": STAFF},
    "tournament-documents": {"post": STAFF},
    "tournament-document": {"delete": STAFF},
    # Published tournaments in the caller's jurisdiction or their regional body's region; see
    # test_tournament_organizers.
    "tournament-overseen": {"get": SIGNED_IN},
    "tournament-stream-report": {"post": SIGNED_IN},
    "tournament-sponsorships": {"get": STAFF},
    "tournament-sponsorship-accept": {"post": STAFF},
    "tournament-sponsorship-decline": {"post": STAFF},
    # Coaching (REQ-047): coaches are found by any player; coachings, bookings, the trainees a coach
    # sees and the coach's notes belong to the two people involved. Another's id is a 404.
    "coaches": {"get": SIGNED_IN},
    # The facility finder (REQ-044): published branch profiles only; see test_facilities.py.
    "facility-list": {"get": SIGNED_IN},
    "facility-detail": {"get": SIGNED_IN},
    "facility-schedule": {"get": SIGNED_IN},
    # Branches near a point the caller sends in the body: the finder's rows plus a distance.
    "facility-nearby": {"post": SIGNED_IN},
    # Facility training slots any player may join (REQ-044); see test_facility_training.py.
    "open-session-list": {"get": SIGNED_IN},
    "open-session-join": {"post": SIGNED_IN},
    "open-session-leave": {"post": SIGNED_IN},
    "coach": {"get": SIGNED_IN},
    "coach-slots": {"get": SIGNED_IN},
    "my-coach-profile": {"get": OWNER, "put": OWNER},
    "my-coach-organizer": {"post": OWNER},
    "my-coach-availability": {"get": OWNER, "put": OWNER},
    "my-coach-calendar": {"get": OWNER},
    "my-coach-notes": {"get": OWNER},
    "my-coach-comment": {"patch": OWNER, "delete": OWNER},
    "my-coachings": {"get": OWNER, "post": OWNER},
    "my-coaching-accept": {"post": OWNER},
    "my-coaching-decline": {"post": OWNER},
    "my-coaching-end": {"post": OWNER},
    "my-trainee": {"get": OWNER},
    "my-trainee-plans": {"post": OWNER},
    "my-trainee-plan": {"get": OWNER, "patch": OWNER, "delete": OWNER},
    "my-trainee-plan-recommendations": {"get": OWNER},
    "my-trainee-plan-items": {"post": OWNER},
    "my-trainee-plan-item": {"patch": OWNER, "delete": OWNER},
    "my-trainee-comments": {"post": OWNER},
    "my-bookings": {"get": OWNER, "post": OWNER},
    "my-booking-confirm": {"post": OWNER},
    "my-booking-decline": {"post": OWNER},
    "my-booking-cancel": {"post": OWNER},
    "organization-drills": {"get": MEMBER, "post": STAFF},
    "organization-drill": {"patch": STAFF, "delete": STAFF},
    # The drill library: the standard drills, your own and your clubs'. Another club's drill is a 404.
    "drill-library-list": {"get": SIGNED_IN},
    "drill-library-detail": {"get": SIGNED_IN},
    # A club's training plans: members read them, training staff write them and get recommendations.
    "organization-training-plans": {"get": MEMBER, "post": STAFF},
    "organization-training-plan": {"get": MEMBER, "patch": STAFF, "delete": STAFF},
    "organization-training-plan-recommendations": {"get": STAFF},
    "organization-training-plan-items": {"post": STAFF},
    "organization-training-plan-item": {"patch": STAFF, "delete": STAFF},
    # Club activities (REQ-039): the list shows anyone signed in the public ones only; the rest is for
    # the audience, and the activities officer runs them. The schedule is for members.
    "organization-activities": {"get": SIGNED_IN, "post": STAFF},
    "organization-activity": {"get": MEMBER, "patch": STAFF},
    "organization-activity-publish": {"post": STAFF},
    "organization-activity-cancel": {"post": STAFF},
    "organization-activity-rsvp": {"post": MEMBER},
    "organization-activity-cost-share": {"post": STAFF},
    "organization-activity-attendees": {"get": MEMBER},
    "organization-activity-invitees": {"get": STAFF},
    # Events beyond the membership (TASK-110): whoever an activity is for checks in while it runs; those
    # who run activities mark attendance; `my-events` lists what invites the caller.
    "organization-activity-check-in": {"post": MEMBER},
    "organization-activity-attendance": {"post": STAFF},
    "my-events": {"get": OWNER},
    # Feedback forms (TASK-131): the host's competition staff build, send and read totals; whoever was
    # asked answers their own (Baraka's here).
    "organization-feedback-forms": {"get": STAFF, "post": STAFF},
    "organization-feedback-form": {"get": STAFF, "patch": STAFF, "delete": STAFF},  # a draft
    "organization-feedback-form-send": {"post": STAFF},
    "organization-feedback-form-closing": {"post": STAFF},
    "organization-feedback-form-totals": {"get": STAFF},
    "organization-feedback-form-export": {"get": STAFF},
    "my-feedback-forms": {"get": OWNER},
    # The financial year and the annual report (TASK-079). Reading a report is open to whoever may: a
    # draft to finance staff, a published one to members, a public one to anybody.
    "organization-finance-settings": {"get": STAFF, "put": STAFF},
    # Money from outside the membership (TASK-124): finance staff only.
    "organization-external-sources": {"get": STAFF, "post": STAFF},
    "organization-external-source": {"patch": STAFF, "delete": STAFF},
    "organization-external-income": {"get": STAFF, "post": STAFF},
    "organization-external-income-reverse": {"post": STAFF},
    "organization-income-totals": {"get": STAFF},
    "organization-annual-reports": {"get": PUBLIC, "post": STAFF},
    "organization-annual-report": {"get": PUBLIC, "patch": STAFF, "delete": STAFF},
    "organization-annual-report-publish": {"post": STAFF},
    "organization-annual-report-amend": {"post": STAFF},
    "organization-annual-report-csv": {"get": PUBLIC},
    "organization-annual-report-pdf": {"get": PUBLIC},
    # Representative squads (TASK-123): competition staff pick; a player answers their own place.
    "organization-squads": {"get": STAFF, "post": STAFF},
    "organization-squad": {"get": STAFF, "patch": STAFF, "delete": STAFF},  # a draft
    "organization-squad-publish": {"post": STAFF},
    "organization-squad-recommendation": {"get": STAFF},
    "organization-squad-places": {"post": STAFF},
    "organization-squad-place-remove": {"post": STAFF},
    "organization-squad-history": {"get": STAFF},
    "organization-squad-place-attendance": {"post": STAFF},
    # Absence penalties (TASK-129): governance staff set rules, propose, issue, waive and decide
    # appeals; a member reads and appeals their own.
    "organization-absence-rules": {"get": STAFF, "put": STAFF},
    "organization-absence-penalties": {"get": STAFF},
    "organization-absence-penalties-propose": {"post": STAFF},
    "organization-absence-penalty-issue": {"post": STAFF},
    "organization-absence-penalty-waive": {"post": STAFF},
    "organization-absence-penalty-appeal": {"post": STAFF},
    "my-absence-penalties": {"get": OWNER},
    "my-absence-penalty-appeal": {"post": OWNER},  # Baraka's penalty
    "my-squad-places": {"get": OWNER},
    "my-squad-place-accept": {"post": OWNER},  # Baraka's place
    "my-squad-place-decline": {"post": OWNER},
    "feedback-form": {"get": OWNER, "put": OWNER},
    "organization-schedule": {"get": MEMBER},
    "organization-schedule-ics": {"get": MEMBER},
    "organization-club-sessions": {"get": STAFF, "post": STAFF},
    "organization-club-session": {"get": STAFF, "patch": STAFF},
    "organization-club-session-cancel": {"post": STAFF},
    # Training rules (TASK-125): members read the slots, the place by name and the check-in rules;
    # training staff set them, and where one session is held.
    "organization-club-session-location": {"post": STAFF},
    "organization-training-rules": {"get": MEMBER, "put": STAFF},
    "organization-club-session-invitations": {"get": STAFF, "post": STAFF},
    "organization-club-session-invitation": {"patch": STAFF},
    "organization-list": {"get": SIGNED_IN, "post": SIGNED_IN},
    # Clubs near a point the caller sends in the body: directory rows plus a distance.
    "organization-nearby": {"post": SIGNED_IN},
    "organization-detail": {"get": SIGNED_IN, "patch": STAFF},
    # What a player sees before joining: location, description, training hours and coming tournaments.
    "organization-profile": {"get": SIGNED_IN},
    "organization-training-hours": {"get": SIGNED_IN, "put": STAFF},
    "organization-permissions": {"get": SIGNED_IN},
    "organization-join-requests": {"get": STAFF, "post": SIGNED_IN},  # anyone may ask to join
    "organization-join-request-approve": {"post": STAFF},
    "organization-join-request-reject": {"post": STAFF},
    "organization-invitations": {"get": STAFF, "post": STAFF},
    "organization-invitation-revoke": {"post": STAFF},
    "organization-guest-list": {"get": STAFF, "post": STAFF},
    "organization-guest-detail": {"patch": STAFF},
    "organization-guest-invite": {"post": STAFF},
    "organization-guest-revoke-invitation": {"post": STAFF},
    "organization-guest-claim-list": {"get": STAFF},
    "organization-guest-claim-retry": {"post": STAFF},
    "organization-guest-claim-reject": {"post": STAFF},
    "organization-roles": {"get": STAFF, "post": STAFF},
    "organization-role": {"patch": STAFF, "delete": STAFF},
    # REQ-045: members see who the admin is; only the admin nominates or cancels; the nominee answers.
    "organization-admin": {"get": MEMBER},
    "organization-admin-nominate": {"post": STAFF},
    "organization-admin-cancel": {"post": STAFF},
    "organization-admin-appoint": {"post": APPROVER},  # platform super admins only, see test_admin_handover
    "me-admin-nomination-list": {"get": OWNER},
    "me-admin-nomination-accept": {"post": OWNER},
    "me-admin-nomination-decline": {"post": OWNER},
    # REQ-045 committees: members see the committee and its history; governance staff change it.
    # Representatives (REQ-045, TASK-108): members read who speaks for them; governance staff of the
    # sender nominate and withdraw, and of the receiving body decide and set the cap.
    "organization-representatives": {"get": MEMBER, "post": STAFF},
    "organization-representatives-cap": {"put": STAFF},
    "organization-representative-withdraw": {"post": STAFF},
    "organization-representative-accept": {"post": STAFF},
    "organization-representative-decline": {"post": STAFF},
    "organization-representative-remove": {"post": STAFF},
    "organization-committee": {"get": MEMBER},
    "organization-committee-history": {"get": MEMBER},
    "organization-committee-candidates": {"get": STAFF},
    "organization-committee-positions": {"post": STAFF},
    "organization-committee-positions-reorder": {"post": STAFF},
    "organization-committee-position": {"patch": STAFF},
    "organization-committee-position-retire": {"post": STAFF},
    "organization-committee-position-holder": {"put": STAFF, "delete": STAFF},
    "organization-committee-position-values": {"patch": STAFF},
    "organization-committee-fields": {"get": STAFF, "post": STAFF},
    "organization-committee-field": {"patch": STAFF},
    "organization-committee-field-retire": {"post": STAFF},
    "organization-committee-field-restore": {"post": STAFF},
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
    "organization-venue-hours": {"put": STAFF},
    "organization-venue-passes": {"get": STAFF, "post": STAFF},
    "organization-venue-pass": {"patch": STAFF},
    "organization-venue-visits": {"get": STAFF, "post": STAFF},
    "organization-venue-visit-active-pass": {"get": STAFF},
    "organization-venue-visit-reverse": {"post": STAFF},
    "organization-facility-takings": {"get": STAFF},  # finances.view, see test_facility_visits.py
    # Tournaments: published ones are for every signed-in player (signed-out pages come with TASK-035);
    # drafts and every change are for the host's competition staff.
    "organization-tournaments": {"get": STAFF, "post": STAFF},
    "tournament-list": {"get": PUBLIC},
    "tournament-dashboard": {"get": STAFF},
    "tournament-schedule": {"get": STAFF, "put": STAFF},
    "tournament-schedule-recommend": {"post": STAFF},
    "tournament-schedule-check": {"post": STAFF},
    "tournament-schedule-publish": {"post": STAFF},
    "tournament-schedule-delay": {"post": STAFF},
    "tournament-schedule-versions": {"get": STAFF},
    "tournament-schedule-version": {"get": STAFF},
    "tournament-schedule-sessions": {"get": STAFF, "post": STAFF},
    "tournament-schedule-session": {"patch": STAFF, "delete": STAFF},
    # Lists only the drafts the caller may approve; see test_authority.
    "tournament-awaiting-approval": {"get": SIGNED_IN},
    "tournament-detail": {"get": PUBLIC, "patch": STAFF, "delete": STAFF},
    "tournament-publish": {"post": STAFF},
    "tournament-request-approval": {"post": STAFF},
    "tournament-reject-approval": {"post": APPROVER},
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
    "tournament-event-entries": {"get": PUBLIC, "post": SIGNED_IN},
    "tournament-event-entry-accept": {"post": STAFF},
    "tournament-event-entry-waitlist": {"post": STAFF},
    "tournament-event-entry-reject": {"post": STAFF},
    "tournament-event-entry-staff-withdraw": {"post": STAFF},
    "tournament-event-entry-check-in": {"post": STAFF},
    "tournament-event-entry-self-check-in": {"post": OWNER},
    "tournament-event-entry-undo-check-in": {"post": STAFF},
    "tournament-event-entry-withdraw": {"post": OWNER},
    "me-entries": {"get": OWNER},
    # Draws: the published draw is for every signed-in player; previews and drawing are for staff.
    "tournament-event-draw": {"get": PUBLIC},
    "tournament-event-standings": {"get": PUBLIC},
    "tournament-event-match": {"get": PUBLIC},  # of the published draw only
    # A match's recap and result card are public for a published tournament (REQ-018).
    "tournament-event-match-recap": {"get": PUBLIC},
    "tournament-event-match-card": {"get": PUBLIC},
    # A team's lineup is handed in by its captain or by staff: who may, and who sees the picks, is
    # covered in tests/test_ties.py. Sending both teams back to choose again is for staff.
    "tournament-event-match-lineup": {"post": SIGNED_IN},
    "tournament-event-match-lineup-reset": {"post": STAFF},
    # Results entered or corrected by the organizers, and what a correction leaves to decide.
    "tournament-event-match-result": {"post": STAFF},
    "tournament-event-match-result-correct": {"post": STAFF},
    "tournament-corrections": {"get": STAFF},
    "tournament-correction-resolve": {"post": STAFF},
    # Scoring: staff say who umpires; the sheet, its events and its confirmation exist only for the
    # umpire assigned to it (tests/test_umpire_scoring.py).
    "tournament-event-umpires": {"get": STAFF},
    "tournament-event-match-umpire": {"post": STAFF},
    "me-scorecards": {"get": OWNER},
    "scorecard-detail": {"get": OWNER},
    "scorecard-events": {"post": OWNER},
    "scorecard-confirm": {"post": OWNER},
    "scorecard-next": {"get": OWNER},
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
    # The match-day control centre (REQ-043, TASK-082).
    "tournament-event-match-call": {"post": STAFF},
    "tournament-event-match-report": {"post": STAFF},
    "tournament-event-match-move": {"post": STAFF},
    "tournament-table-block": {"post": STAFF},
    "tournament-table-unblock": {"post": STAFF},
    "tournament-table-umpire": {"put": STAFF},
    "tournament-umpires": {"get": STAFF, "post": STAFF},
    "tournament-order-of-play": {"get": PUBLIC},
    "tournament-order-of-play-stages": {"put": STAFF},
    "tournament-order-of-play-release": {"put": STAFF},
    "tournament-order-of-play-player": {"put": STAFF, "delete": STAFF},
    "tournament-order-of-play-move": {"post": STAFF},
    "tournament-umpire-candidates": {"get": STAFF},
    "tournament-umpire": {"delete": STAFF},
    "tournament-check-in-desk": {"get": STAFF},
    "tournament-match-day-log": {"get": STAFF},
    "tournament-scoring": {"get": STAFF},
    "tournament-scoring-conflict-resolve": {"post": STAFF},
    "tournament-event-draw-preview": {"post": STAFF},
    "tournament-event-draw-publish": {"post": STAFF},
    "player-directory": {"get": SIGNED_IN},
    "player-detail": {"get": PUBLIC},  # signed out, the name of a listed player with competition records
    "player-ratings": {"get": PUBLIC},  # signed out, only players with competition records
    "rankings": {"get": PUBLIC},  # a club's own ranking needs a session
    "club-rankings": {"get": PUBLIC},
    "geography-rankings": {"get": PUBLIC},
}

SPARE_TABLE = "00000000-0000-4000-8000-0000000000aa"  # a free table for the dispatch route
MOVE_TABLE = "00000000-0000-4000-8000-0000000000ab"  # a free table to move a match to
FAITH_MEMBERSHIP = "00000000-0000-4000-8000-0000000000fa"  # Faith, for the admin nomination bodies
UMPIRE_USER = "00000000-0000-4000-8000-0000000000c1"  # a member on the Scored Cup's umpires
# Entries with known ids, so a result can name its winner.
ENTERED_WINNER = "00000000-0000-4000-8000-0000000000b1"
CORRECTED_WINNER = "00000000-0000-4000-8000-0000000000b2"

NYALI_CUP = "00000000-0000-4000-8000-0000000000c9"  # a published Nyali tournament Coast can sponsor

# Bodies that would succeed for someone allowed, so a refusal is about access and not about validation.
# Routes that take a file upload rather than JSON.
# Routes the receiving body's staff call, so they are tried on the regional body, not the club.
BODY_SIDE = {
    "organization-representatives-cap",
    "organization-representative-accept",
    "organization-representative-decline",
    "organization-representative-remove",
}
MULTIPART = {
    "organization-expense-receipt",
    "tournament-cover",
    "tournament-documents",
    "organization-meeting-documents",
}
PDF = b"%PDF-1.4\n%%EOF\n"


def order_time(hour: int) -> datetime:
    """Tomorrow at `hour`, in the Order Cup's timezone."""
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(Tournament.objects.get(name="Order Cup").timezone)
    return datetime.combine(
        timezone.localdate() + timedelta(days=1), datetime.min.time(), tzinfo=zone
    ).replace(hour=hour)


def order_stages() -> dict:
    match = Match.objects.get(draw__event__tournament__name="Order Cup")
    return {"stages": [{"event_id": str(match.draw.event_id), "stage": match.stage}]}


def pdf_upload():
    from io import BytesIO

    out = BytesIO(PDF)
    out.name = "rules.pdf"
    return out


BODIES = {
    ("auth-me-email", "post"): {"email": "new.address@example.com"},
    ("tournament-ceremony", "put"): {"location": "Main hall"},
    ("tournament-review", "put"): {"went_well": "Ran to time"},
    ("tournament-announcements", "post"): {"scope": "tournament"},
    ("tournament-announcement", "patch"): {"body": "Edited"},
    ("tournament-ceremony-awards", "post"): {"title": "Fair play"},
    ("tournament-ceremony-award", "patch"): {"prize": "Trophy"},
    ("tournament-ceremony-reorder", "post"): lambda: {
        "awards": [str(pk) for pk in Award.objects.order_by("-order").values_list("id", flat=True)]
    },
    ("organization-agenda", "post"): {"title": "County open", "starts_on": "2027-02-01"},
    ("organization-agenda-item", "patch"): {"title": "Renamed date"},
    ("organization-articles", "post"): {"title": "News", "body": "Hello clubs"},
    ("organization-article", "patch"): {"summary": "Short"},
    ("organization-meetings", "post"): lambda: {
        "title": "Committee",
        "starts_at": (timezone.now() + timedelta(days=3)).isoformat(),
        "ends_at": (timezone.now() + timedelta(days=3, hours=2)).isoformat(),
    },
    ("organization-meeting", "patch"): {"location": "Clubhouse"},
    ("organization-meeting-cancel", "post"): {"reason": "Venue closed"},
    ("organization-meeting-minutes", "post"): {"minutes": "Agreed the budget."},
    ("organization-meeting-minutes-amendments", "post"): {"text": "Corrected the date."},
    ("organization-meeting-action-item", "post"): {"status": "done"},
    ("organization-meeting-documents", "post"): lambda: {"title": "Accounts", "file": pdf_upload()},
    ("organization-meeting-answer", "post"): {"answer": "attending"},
    ("organization-meeting-attendance", "post"): lambda: {
        "invitee": str(MeetingInvitee.objects.get(meeting__title="MARK-MEETING-RUNNING").id),
        "attendance": "late",
    },
    ("organization-meeting-penalty", "patch"): {"status": "waived"},
    ("organization-sponsorships", "post"): {"tournament_id": NYALI_CUP, "amount_minor": 100000},
    ("tournament-streams", "post"): {"url": "https://www.youtube.com/live/coast-open"},
    ("tournament-stream", "patch"): {"title": "Table 1"},
    ("tournament-stream-report", "post"): {"reason": "broken"},
    ("tournament-schedule", "put"): {"slots": []},
    ("tournament-schedule-check", "post"): {"slots": []},
    ("tournament-schedule-delay", "post"): {"table_id": SPARE_TABLE, "minutes": 20, "reason": "late_start"},
    ("tournament-schedule-sessions", "post"): {
        "day": "2026-12-05",
        "starts": "09:00",
        "ends": "13:00",
        "table_ids": [SPARE_TABLE],
    },
    ("tournament-schedule-session", "patch"): {"name": "Morning"},
    ("organization-detail", "patch"): {"country": "KE", "region": "Mombasa", "town": "Mombasa"},
    ("organization-training-hours", "put"): {"hours": [{"weekday": 1, "starts": "18:00", "ends": "20:00"}]},
    ("organization-invitations", "post"): {"email": "newcomer@example.com"},
    ("organization-guest-list", "post"): {"display_name": "Walk-in Guest"},
    ("organization-guest-detail", "patch"): {"display_name": "Kassim the Guest"},
    ("organization-guest-invite", "post"): {"email": "kassim@example.com"},
    ("organization-guest-claim-retry", "post"): {"note": "Checked again"},
    ("organization-guest-claim-reject", "post"): {"note": "Not the same player"},
    ("organization-roles", "post"): {"name": "Scorers", "permissions": []},
    ("organization-role", "patch"): {"name": "Renamed"},
    ("organization-member-roles", "put"): {"roles": []},
    ("organization-admin-nominate", "post"): {"membership_id": FAITH_MEMBERSHIP},
    ("organization-admin-appoint", "post"): {"membership_id": FAITH_MEMBERSHIP, "reason": "Test"},
    ("organization-representatives", "post"): {"membership_id": FAITH_MEMBERSHIP},
    ("organization-representatives-cap", "put"): {"cap": 5},
    ("organization-committee-positions", "post"): {"name": "Youth officer"},
    # Every active position, read when the call is made (the create above adds one).
    ("organization-committee-positions-reorder", "post"): lambda: {
        "positions": [
            str(pk)
            for pk in CommitteePosition.objects.filter(
                organization__name="Coast Spinners", retired_at__isnull=True
            ).values_list("id", flat=True)
        ]
    },
    ("organization-committee-position", "patch"): {"name": "Renamed seat"},
    ("organization-committee-position-holder", "put"): {"membership_id": FAITH_MEMBERSHIP},
    ("organization-committee-position-values", "patch"): {"values": {}},
    ("organization-committee-fields", "post"): {"label": "Term notes", "kind": "text"},
    ("organization-committee-field", "patch"): {"label": "Renamed committee field"},
    ("personal-match-detail", "patch"): {"label": "Changed"},
    ("me-membership-fields", "patch"): {"values": {}},
    ("organization-member-fields", "patch"): {"values": {}},
    ("organization-member-field-list", "post"): {"label": "Locker", "kind": "text"},
    ("organization-member-field", "patch"): {"label": "Renamed field"},
    ("organization-venues", "post"): {"name": "Second hall", "town": "Mombasa"},
    ("organization-drills", "post"): {"title": "Ghost serve", "instructions": "Short and low."},
    ("organization-drill", "patch"): {"focus": "Footwork"},
    ("organization-training-plans", "post"): {"title": "Week", "period": "week", "starts_on": "2026-11-30"},
    ("organization-training-plan", "patch"): {"goal": "Footwork"},
    ("organization-training-plan-items", "post"): {"kind": "checklist", "title": "Shadow play"},
    ("organization-training-plan-item", "patch"): {"completed": True},
    ("organization-club-sessions", "post"): lambda: {
        "title": "Extra session",
        "table_ids": [str(Table.objects.get(label="Training table").id)],
        "starts_at": (timezone.now() + timedelta(days=5)).replace(microsecond=0).isoformat(),
        "ends_at": (timezone.now() + timedelta(days=5, hours=2)).replace(microsecond=0).isoformat(),
    },
    ("organization-club-session", "patch"): {"title": "Renamed session"},
    ("organization-activities", "post"): lambda: {
        "title": "Fun day",
        "kind": "fun_day",
        "starts_at": (timezone.now() + timedelta(days=6)).isoformat(),
        "ends_at": (timezone.now() + timedelta(days=6, hours=4)).isoformat(),
    },
    ("organization-activity", "patch"): {"place": "Moved to the beach"},
    ("organization-activity-cancel", "post"): {"reason": "Rain"},
    ("organization-activity-rsvp", "post"): {"answer": "maybe"},
    ("organization-feedback-forms", "post"): lambda: {
        "title": "After the cup",
        "tournament_id": str(Tournament.objects.get(name="Published Cup").id),
    },
    ("organization-feedback-form", "patch"): {"title": "Renamed form"},
    ("organization-finance-settings", "put"): {"year_end_month": 12, "year_end_day": 31},
    ("organization-external-sources", "post"): {"name": "Gate takings"},
    ("organization-external-source", "patch"): {"active": False},
    ("organization-external-income", "post"): lambda: {
        "source_id": str(ExternalSource.objects.get(name="MARK-SOURCE-USED").id),
        "amount_minor": 5000,
        "received_on": str(timezone.localdate()),
        "request_key": str(uuid.uuid4()),
    },
    ("organization-external-income-reverse", "post"): {"reason": "Entered twice"},
    ("organization-annual-reports", "post"): lambda: {"period_end": f"{timezone.localdate().year - 5}-12-31"},
    ("organization-annual-report", "patch"): {"narrative": "A steady year."},
    ("organization-squads", "post"): lambda: {
        "title": "Away cup",
        "starts_on": str(timezone.localdate() + timedelta(days=20)),
        "ends_on": str(timezone.localdate() + timedelta(days=21)),
        "slots": [{"label": "Team", "places": 3}],
    },
    ("organization-squad", "patch"): {"notes": "Bring whites"},
    ("organization-squad-place-attendance", "post"): {"attended": False},
    ("organization-absence-rules", "put"): {"rules": [{"applies_to": "training", "kind": "warning"}]},
    ("organization-absence-penalty-waive", "post"): {"reason": "Excused"},
    ("organization-absence-penalty-appeal", "post"): {"upheld": False, "note": "Stands"},
    ("my-absence-penalty-appeal", "post"): {"text": "I was there"},
    ("organization-squad-places", "post"): lambda: {
        "user_id": str(Membership.objects.get(user__email="faith.listed@coast.example").user_id),
        "slot": "cccccccccccc",
        "reason": "Asked to go",
    },
    ("organization-feedback-form-send", "post"): lambda: {
        "closes_at": (timezone.now() + timedelta(days=5)).isoformat()
    },
    ("organization-feedback-form-closing", "post"): lambda: {
        "closes_at": (timezone.now() + timedelta(days=9)).isoformat()
    },
    ("feedback-form", "put"): {"answers": {"aaaaaaaaaaaa": "MARK-FEEDBACK-EDITED"}},
    ("organization-activity-attendance", "post"): lambda: {
        "rsvp": str(Rsvp.objects.get(activity__title="Running night").id),
        "attended": True,
    },
    ("organization-activity-cost-share", "post"): lambda: {
        "amount_minor": 50000,
        "due_on": timezone.localdate().isoformat(),
    },
    ("organization-soda-policy", "put"): {"games_enabled": True, "stakes_enabled": False},
    ("organization-announcements", "post"): {"title": "Hall closed", "audience": "members"},
    ("organization-charges", "post"): lambda: {
        "member_id": str(Charge.objects.get(purpose="MARK-CHARGE").member_id),
        "purpose": "Kit fund",
        "amount_minor": 5000,
    },
    ("organization-charge-waive", "post"): {"reason": "Honorary member"},
    ("organization-payments", "post"): lambda: {
        "payer_id": str(Charge.objects.get(purpose="MARK-CHARGE").member_id),
        "amount_minor": 1000,
        "method": "cash",
        "received_on": "2026-11-19",
        "request_key": str(uuid.uuid4()),
    },
    ("organization-payment-allocate", "post"): lambda: {
        "charge_id": str(Charge.objects.get(purpose="Ball fund").id),
        "amount_minor": 100,
    },
    ("organization-payment-reverse", "post"): {"reason": "Recorded twice"},
    ("organization-campaigns", "post"): lambda: {
        "title": "Net fund",
        "amount_minor": 1000,
        "cadence": "once",
        "starts_on": (timezone.localdate() + timedelta(days=90)).isoformat(),
    },
    ("organization-campaign", "patch"): {"amount_minor": 2000},
    ("organization-expenses", "post"): lambda: {
        "description": "Chalk",
        "amount_minor": 300,
        "spent_on": timezone.localdate().isoformat(),
    },
    ("organization-expense-reverse", "post"): {"reason": "Entered twice"},
    ("organization-welfare-projects", "post"): {"title": "Support the juniors' trip"},
    ("organization-welfare-project", "patch"): {"show_contributors": True},
    ("organization-welfare-contributions", "post"): lambda: {
        "contributor_id": str(Charge.objects.get(purpose="MARK-CHARGE").member_id),
        "amount_minor": 5000,
        "method": "cash",
        "received_on": timezone.localdate().isoformat(),
        "request_key": str(uuid.uuid4()),
    },
    ("organization-welfare-contribution-reverse", "post"): {"reason": "Wrong member"},
    ("organization-welfare-expenses", "post"): lambda: {
        "description": "Visit gift",
        "amount_minor": 3000,
        "spent_on": timezone.localdate().isoformat(),
    },
    ("organization-expense-receipt", "put"): lambda: {"file": image_upload("PNG", (64, 64), "slip.png")},
    ("tournament-cover", "put"): lambda: {"file": image_upload("PNG", (64, 64), "cover.png")},
    ("tournament-documents", "post"): lambda: {"title": "Rules", "file": pdf_upload()},
    ("organization-campaign-terms", "post"): lambda: {
        "member_id": str(Charge.objects.get(purpose="MARK-CHARGE").member_id),
        "amount_minor": 500,
    },
    ("my-notification-preferences", "put"): {"preferences": [{"category": "soda", "enabled": False}]},
    ("organization-external-events", "post"): {
        "name": "Kilifi Open",
        "organizer": "Kilifi TT",
        "starts_on": "2027-03-01",
        "ends_on": "2027-03-01",
        "town": "Kilifi",
    },
    ("organization-external-event", "patch"): {"venue": "Kasarani"},
    ("organization-external-event-live", "post"): {"live": True},
    ("external-event-reject", "post"): {"note": "Duplicate"},
    ("external-event-report", "post"): {"reason": "broken"},
    ("soda-game-counter", "post"): {"play_at": "2026-12-01T17:00:00Z"},
    ("soda-game-result", "post"): {"games": [[11, 5], [11, 5]]},
    ("soda-game-dispute", "post"): {"reason": "No"},
    ("soda-game-share", "post"): {"share": True},
    ("organization-club-session-invitations", "post"): lambda: {
        "user_ids": [
            str(
                Membership.objects.active()
                .filter(organization=ClubSession.objects.get(notes="MARK-SESSION-NOTE").organization)
                .values_list("user_id", flat=True)
                .first()
            )
        ]
    },
    ("organization-club-session-invitation", "patch"): {"attended": None},
    ("organization-club-session-location", "post"): {"latitude": -4.05, "longitude": 39.66, "label": "Beach"},
    ("organization-training-rules", "put"): {"radius_m": 200},
    ("my-session-invitation-apologise", "post"): {"reason": "Away"},
    ("my-session-invitation-check-in", "post"): {"latitude": -4.0439, "longitude": 39.6682, "accuracy_m": 20},
    ("organization-venue", "patch"): {"town": "Nyali"},
    ("organization-venue-tables", "post"): {"label": "Table 9"},
    ("organization-venue-table", "patch"): {"label": "Table 10"},
    ("organization-venue-passes", "post"): {"name": "Week pass", "kind": "week", "amount_minor": 90000},
    ("organization-venue-pass", "patch"): {"amount_minor": 25000},
    ("organization-venue-visits", "post"): lambda: {
        "pass_id": str(Pass.objects.get(name="Day pass").id),
        "walk_in_name": "Door visitor",
        "method": "cash",
    },
    ("organization-venue-visit-reverse", "post"): {"reason": "Recorded by mistake"},
    ("organization-booking-reject", "post"): {"reason": "Closed for a tournament"},
    ("organization-venue-hours", "put"): {
        "hours": [{"weekday": 0, "opens": "08:00", "closes": "20:00"}],
        "closures": [],
    },
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
    ("tournament-umpires", "post"): {"user_id": UMPIRE_USER},
    ("tournament-order-of-play-stages", "put"): order_stages,
    ("tournament-order-of-play-release", "put"): {"release_at": None},
    ("tournament-order-of-play-player", "put"): lambda: {"at": order_time(13).isoformat(), "move": True},
    ("tournament-order-of-play-move", "post"): lambda: {"scheduled_at": order_time(15).isoformat()},
    ("tournament-table-umpire", "put"): {"user_id": None},
    ("tournament-dispatch-auto", "post"): {"enabled": False},
    ("tournament-event-match-recall", "post"): {"reason": "Wrong table"},
    ("tournament-event-match-report", "post"): {"side": "a"},
    ("tournament-event-match-move", "post"): {"table_id": MOVE_TABLE, "reason": "Light out"},
    ("tournament-table-block", "post"): {"reason": "out_of_service"},
    ("tournament-event-match-result", "post"): {"winner_entry_id": ENTERED_WINNER, "outcome": "walkover"},
    ("tournament-event-match-result-correct", "post"): {
        "winner_entry_id": CORRECTED_WINNER,
        "outcome": "walkover",
        "reason": "Entered for the wrong player",
    },
    ("tournament-correction-resolve", "post"): {"choice": "keep", "note": "Both players agree"},
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
        self.faith_membership = Membership.objects.create(
            id=FAITH_MEMBERSHIP, organization=self.coast, user=self.faith
        )
        self.nomination = AdminHandover.objects.create(
            organization=self.coast, from_user=self.amina, to_user=self.baraka, created_by=self.amina
        )
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
        self.match_note = MatchNote.objects.create(
            owner=self.baraka, personal_match=self.match, observations="MARK-BARAKA-OBSERVATION"
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
        # Training: Baraka's equipment, drill and plan are his alone; Coast's drill is for its members.
        Equipment.objects.create(user=self.baraka, blade="MARK-BARAKA-BLADE")
        self.baraka_drill = Drill.objects.create(
            owner=self.baraka, title="MARK-BARAKA-DRILL", instructions="Private"
        )
        # Kito coaches Baraka (REQ-047). He isn't one of the viewers: everything between them is for
        # Baraka alone here, and Kito's own reach is covered in test_coaching.
        self.kito = make_user("kito.coach@else.example", display_name="Kito Coach")
        CoachProfile.objects.create(user=self.kito, headline="Serve and footwork coach")
        Availability.objects.create(coach=self.kito, weekday=0, starts="08:00", ends="12:00")
        self.coaching = Coaching.objects.create(
            coach=self.kito,
            trainee=self.baraka,
            requested_by=self.baraka,
            status=Coaching.Status.ACTIVE,
            message="MARK-COACHING-MESSAGE",
        )
        self.booking = Booking.objects.create(
            coach=self.kito,
            trainee=self.baraka,
            starts_at=datetime(2026, 12, 7, 6, tzinfo=UTC),
            ends_at=datetime(2026, 12, 7, 7, tzinfo=UTC),
            note="MARK-BOOKING-NOTE",
        )
        self.baraka_plan = TrainingPlan.objects.create(
            owner=self.baraka, coach=self.kito, title="MARK-BARAKA-PLAN"
        )
        self.coach_note = MatchComment.objects.create(
            coach=self.kito, trainee=self.baraka, personal_match=self.match, body="MARK-COACH-NOTE"
        )
        self.baraka_item = PlanItem.objects.create(
            plan=self.baraka_plan, kind=PlanItem.Kind.CHECKLIST, title="MARK-BARAKA-ITEM"
        )
        self.club_drill = Drill.objects.create(
            organization=self.coast, title="MARK-CLUB-DRILL", instructions="For members"
        )
        self.club_plan = TrainingPlan.objects.create(
            organization=self.coast, title="MARK-CLUB-PLAN", goal_skills=["footwork"]
        )
        self.club_item = PlanItem.objects.create(
            plan=self.club_plan, kind=PlanItem.Kind.CHECKLIST, title="MARK-CLUB-ITEM"
        )
        self.spare_club_plan = TrainingPlan.objects.create(organization=self.coast, title="Spare club plan")
        # A club session (REQ-027) in its own room, with Baraka invited; another one to cancel.
        room = Venue.objects.create(organization=self.coast, name="Training room", town="Mombasa")
        room_table = Table.objects.create(venue=room, label="Training table")
        starts = timezone.now() + timedelta(days=2)
        self.club_session = ClubSession.objects.create(
            organization=self.coast,
            title="Squad",
            notes="MARK-SESSION-NOTE",
            starts_at=starts,
            ends_at=starts + timedelta(hours=2),
        )
        self.club_session.tables.set([room_table])
        self.session_invitation = SessionInvitation.objects.create(
            session=self.club_session, user=self.baraka
        )
        # Faith sent an apology with a reason: hers and the training staff's to read.
        SessionInvitation.objects.create(
            session=self.club_session,
            user=self.faith,
            status=SessionInvitation.Status.DECLINED,
            apologised_at=timezone.now(),
            apology_reason="MARK-APOLOGY",
        )
        # Where Coast trains: members see the name of the place, training staff its coordinates too.
        TrainingRules.objects.create(
            organization=self.coast,
            latitude="-4.043911",
            longitude="39.668207",
            location_label="MARK-TRAINING-PLACE",
        )
        # An external event Coast submitted, still waiting for a curator.
        self.external = ExternalEvent.objects.create(
            submitted_by_org=self.coast,
            submitted_by=self.amina,
            name="Nairobi Classic",
            organizer="Nairobi TT",
            starts_on=timezone.localdate() + timedelta(days=30),
            ends_on=timezone.localdate() + timedelta(days=30),
            town="Nairobi",
            entry_info="MARK-EXTERNAL-PENDING",
        )
        # Faith owes an event fee and the ball fund, and paid twice; one payment to reverse.
        self.charge = Charge.objects.create(
            organization=self.coast, member=self.faith, purpose="MARK-CHARGE", amount_minor=100000
        )
        Charge.objects.create(
            organization=self.coast, member=self.faith, purpose="Ball fund", amount_minor=5000
        )

        # Dues campaigns whose first period is still to come, so reading the ledger generates nothing.
        def dues_campaign(title):
            return Campaign.objects.create(
                organization=self.coast,
                title=title,
                amount_minor=50000,
                cadence="monthly",
                starts_on=timezone.localdate() + timedelta(days=60),
            )

        self.campaign = dues_campaign("MARK-CAMPAIGN")
        self.campaign_to_close = dues_campaign("Old dues")
        # Spending on the campaign, with a private receipt, and one to reverse.
        self.receipt = Attachment.store(
            owner=self.amina,
            purpose=Attachment.Purpose.RECEIPT,
            content=b"receipt",
            content_type="image/webp",
        )
        self.expense = Expense.objects.create(
            organization=self.coast,
            campaign=self.campaign,
            description="MARK-EXPENSE",
            amount_minor=2000,
            spent_on=timezone.localdate(),
            receipt=self.receipt,
        )

        # A welfare project with one anonymous gift from Faith; more to hide, to close and to make a due.
        def project(title, **extra):
            return WelfareProject.objects.create(
                organization=self.coast, title=title, suggested_minor=5000, **extra
            )

        self.welfare = project("MARK-WELFARE", description="MARK-WELFARE-DESC")
        self.welfare_to_hide = project("Hide me")
        self.welfare_to_close = project("Close me")
        self.welfare_to_due = project("Make me a due")
        self.welfare_contribution = welfare.contribute(
            self.welfare,
            self.amina,
            timezone.localdate(),
            contributor=self.faith,
            anonymous=True,
            request_key=uuid.uuid4(),
            amount_minor=5000,
            currency="KES",
            method="mpesa",
            reference="MARK-WELFARE-REF",
            received_on=timezone.localdate(),
        )
        self.expense_to_reverse = Expense.objects.create(
            organization=self.coast, description="Old nets", amount_minor=1000, spent_on=timezone.localdate()
        )

        def payment(reference):
            return Payment.objects.create(
                organization=self.coast,
                payer=self.faith,
                amount_minor=50000,
                method="cash",
                reference=reference,
                received_on=timezone.localdate(),
                request_key=uuid.uuid4(),
            )

        self.payment = payment("MARK-PAYMENT-REF")
        self.payment_to_reverse = payment("Second")
        # An alert in Baraka's inbox.
        self.alert = Notification.objects.create(
            recipient=self.baraka, category="announcement", title="MARK-ALERT", subject="matrix:1"
        )
        # A browser that shows Baraka's alerts as push messages.
        self.push_device = PushSubscription.objects.create(
            user=self.baraka,
            endpoint="https://fcm.googleapis.com/fcm/send/matrix-device",
            p256dh="MARK-PUSH-KEY",
            auth="MARK-PUSH-AUTH",
            label="Chrome on Android",
        )
        # A soda game Baraka challenged Imani to, with a pledge only the two of them may see.
        self.soda = Challenge.objects.create(
            challenger=self.baraka,
            challenged=self.imani,
            message="MARK-SODA-MESSAGE",
            stake_note="MARK-SODA-STAKE",
        )
        # Club activities: a published members' night, a draft, and one to cancel.
        later = timezone.now() + timedelta(days=4)
        self.activity = Activity.objects.create(
            organization=self.coast,
            title="Members night",
            description="MARK-ACTIVITY-PRIVATE",
            starts_at=later,
            ends_at=later + timedelta(hours=3),
            status=Activity.Status.PUBLISHED,
        )
        self.activity_draft = Activity.objects.create(
            organization=self.coast,
            title="Draft night",
            description="MARK-ACTIVITY-DRAFT",
            starts_at=later,
            ends_at=later + timedelta(hours=3),
        )
        self.activity_to_cancel = Activity.objects.create(
            organization=self.coast,
            title="To cancel",
            starts_at=later,
            ends_at=later + timedelta(hours=3),
            status=Activity.Status.PUBLISHED,
        )
        self.activity_to_share = Activity.objects.create(
            organization=self.coast,
            title="Share my cost",
            starts_at=later,
            ends_at=later + timedelta(hours=3),
            status=Activity.Status.PUBLISHED,
        )
        Rsvp.objects.create(activity=self.activity_to_share, user=self.baraka, answer=Rsvp.Answer.GOING)
        self.activity_running = Activity.objects.create(
            organization=self.coast,
            title="Running night",
            starts_at=timezone.now() - timedelta(minutes=10),
            ends_at=timezone.now() + timedelta(hours=2),
            status=Activity.Status.PUBLISHED,
        )
        Rsvp.objects.create(activity=self.activity_running, user=self.baraka, answer=Rsvp.Answer.GOING)
        # An event for one named outsider: not for the club's other members.
        named_event = Activity.objects.create(
            organization=self.coast,
            title="Named evening",
            description="MARK-EVENT-NAMED",
            audience=Activity.Audience.NAMED,
            starts_at=later,
            ends_at=later + timedelta(hours=3),
            status=Activity.Status.PUBLISHED,
        )
        named_event.invitees.add(self.chiku)
        self.session_to_cancel = ClubSession.objects.create(
            organization=self.coast,
            title="To cancel",
            starts_at=starts + timedelta(days=1),
            ends_at=starts + timedelta(days=1, hours=2),
        )
        # The committee (REQ-045): Faith holds a seat that grants a staff-only role; Grace held it before.
        # One committee field members see and one for governance staff, each with a value on the seat.
        self.position = CommitteePosition.objects.create(
            organization=self.coast, name="MARK-POSITION", grants_role=self.custom_role
        )
        self.vacant_position = CommitteePosition.objects.create(
            organization=self.coast, name="Vacant seat", order=1
        )
        self.retiring_position = CommitteePosition.objects.create(
            organization=self.coast, name="Retiring seat", order=2
        )
        grace_membership = Membership.objects.get(organization=self.coast, user=self.grace)
        PositionHolder.objects.create(
            position=self.position,
            membership=grace_membership,
            started_on="2025-01-01",
            ended_on="2025-12-31",
            ended_at=timezone.now(),
            end_reason=PositionHolder.EndReason.REPLACED,
        )
        PositionHolder.objects.create(
            position=self.position, membership=self.faith_membership, started_on="2026-01-01"
        )
        for label, visibility in (("MARK-CFIELD-MEMBER", "member"), ("MARK-CFIELD-STAFF", "staff")):
            made = CommitteeField.objects.create(
                organization=self.coast, label=label, kind="text", visibility=visibility
            )
            CommitteeFieldValue.objects.create(
                field=made, position=self.position, value=label.replace("CFIELD", "CVALUE")
            )
        self.committee_field = made

        # A venue with a table in use and one switched off; a second venue switched off.
        self.venue = Venue.objects.create(organization=self.coast, name="Makadara Hall", town="Mombasa")
        self.table = Table.objects.create(venue=self.venue, label="Table 1")
        Table.objects.create(venue=self.venue, label="MARK-TABLE-OFF", position=1, active=False)
        Venue.objects.create(organization=self.coast, name="MARK-VENUE-OFF", town="Mombasa", active=False)
        # Baraka asked to book Table 1; another request to decline and one to cancel.
        soon = timezone.now() + timedelta(days=5)

        def booking(note):
            made = TableBooking.objects.create(
                venue=self.venue,
                requester=self.baraka,
                starts_at=soon,
                ends_at=soon + timedelta(hours=1),
                note=note,
            )
            made.tables.set([self.table])
            return made

        self.booking = booking("MARK-TABLE-BOOKING")
        self.booking_to_reject = booking("Second")
        self.booking_to_cancel = booking("Third")
        # Door visits (REQ-044): a walk-in whose name stays with the facility's staff, and Baraka's own.
        self.day_pass = Pass.objects.create(venue=self.venue, name="Day pass", kind="day", amount_minor=20000)
        today = timezone.localdate()
        self.walk_in = Visit.objects.create(
            venue=self.venue,
            pass_sold=self.day_pass,
            walk_in_name="MARK-WALK-IN",
            amount_minor=20000,
            currency="KES",
            method="mpesa",
            reference="MARK-VISIT-REF",
            visited_on=today,
            valid_until=today,
            recorded_by=self.amina,
        )
        Visit.objects.create(
            venue=self.venue,
            pass_sold=self.day_pass,
            player=self.baraka,
            amount_minor=20000,
            currency="KES",
            method="cash",
            visited_on=today,
            valid_until=today,
            recorded_by=self.amina,
        )

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
        self.regional_draft = tournament("Regional approval", status.DRAFT)
        self.regional_draft.scope = Tournament.Scope.REGIONAL
        self.regional_draft.save(update_fields=["scope"])
        self.deletable = tournament("MARK-DELETABLE-CUP", status.DRAFT)  # the staff checks delete it
        self.published = tournament("Published Cup", status.PUBLISHED)
        self.to_cancel = tournament("Doomed Cup", status.PUBLISHED)
        self.running = tournament("Running Cup", status.IN_PROGRESS)
        self.finishing = tournament("Finishing Cup", status.IN_PROGRESS, Event.Status.COMPLETED)
        self.playing = tournament("Playing Cup", status.IN_PROGRESS, Event.Status.IN_PROGRESS)
        self.reviewed = tournament("Reviewed Cup", status.COMPLETED, Event.Status.COMPLETED)
        TournamentReview.objects.create(
            tournament=self.reviewed, went_wrong="MARK-REVIEW", actions=[{"text": "MARK-REVIEW-ACTION"}]
        )
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
        umpire = User.objects.create(
            id=UMPIRE_USER, email="umpire.listed@coast.example", display_name="Upendo"
        )
        Membership.objects.create(organization=self.coast, user=umpire)
        TournamentUmpire.objects.create(tournament=self.scored_cup, user=umpire)
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
        def under_way(name, players, second_id=None):
            cup = tournament(name, status.IN_PROGRESS, Event.Status.IN_PROGRESS)
            for label in players:
                made = Entry.objects.create(
                    id=second_id if second_id and label == players[1] else uuid.uuid4(),
                    event=cup.event,
                    status=Entry.Status.ACCEPTED,
                    checked_in_at=timezone.now(),
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
        # A match on a table for the control centre's call, report and move routes.
        self.control_cup, self.called = under_way("Control Cup", ("k1", "k2"))
        reservations.dispatch(
            self.called, Table.objects.create(venue=self.venue, label="Control table"), self.amina
        )
        Table.objects.create(id=MOVE_TABLE, venue=self.venue, label="Move table")
        # For the result routes: a match to enter a result for, a decided one to correct, and a later
        # match a correction has put in question.
        self.result_cup, self.to_decide = under_way("Result Cup", ("e1", "e2"), ENTERED_WINNER)
        self.corrected_cup, self.decided = under_way("Corrected Cup", ("c1", "c2"), CORRECTED_WINNER)
        first = next(e for e in (self.decided.entry_a, self.decided.entry_b) if str(e.id) != CORRECTED_WINNER)
        drawing.record_result(self.decided, first, outcome="walkover")
        self.question_cup, self.in_question = under_way("Question Cup", ("q1", "q2"))
        # A day schedule with a session, a published version and a working plan still to publish.
        self.planned_cup, planned = under_way("Planned Cup", ("s1", "s2"))
        Match.objects.filter(pk=planned.pk).update(
            draft_table=self.spare_table, draft_at=datetime(2026, 12, 5, 7, 0, tzinfo=UTC)
        )
        self.session = ScheduleSession.objects.create(
            tournament=self.planned_cup, day="2026-12-05", starts="09:00", ends="21:00"
        )
        self.session.tables.add(self.spare_table)
        ScheduleVersion.objects.create(tournament=self.planned_cup, number=1, kind="published")
        # The order of play (REQ-053): play starts tomorrow, its one match published at noon.
        self.order_cup, ordered = under_way("Order Cup", ("o1", "o2"))
        tomorrow = timezone.localdate() + timedelta(days=1)
        Tournament.objects.filter(pk=self.order_cup.pk).update(starts_on=tomorrow, ends_on=tomorrow)
        Match.objects.filter(pk=ordered.pk).update(
            planned_table=self.spare_table,
            scheduled_at=order_time(12),
            draft_table=self.spare_table,
            draft_at=order_time(12),
        )
        ScheduleVersion.objects.create(tournament=self.order_cup, number=1, kind="published")
        self.order_player = User.objects.get(email="o1@dispatch.example")
        self.resolution = Resolution.objects.create(
            event=self.question_cup.event,
            match=self.in_question,
            side="a",
            old_entry=self.in_question.entry_a,
            cause=OfficialResult.objects.get(match=self.decided),
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

        # A draft award ceremony of the published cup, with Baraka named for one award.
        ceremony = Ceremony.objects.create(tournament=self.published, location="MARK-CEREMONY-PLACE")
        self.award = Award.objects.create(
            ceremony=ceremony, title="MARK-AWARD-DRAFT", recipient=self.baraka, order=1
        )
        self.award_to_present = Award.objects.create(ceremony=ceremony, title="Best umpire", order=2)
        # Results announcements of the published cup: a draft (private to its staff), one to publish, one out.
        news = {"tournament": self.published, "scope": "tournament", "title": "Results"}
        self.news_draft = Announcement.objects.create(**news, body="MARK-ANNOUNCEMENT-DRAFT")
        self.news_to_publish = Announcement.objects.create(**news, body="Ready")
        self.news_out = Announcement.objects.create(
            **news, body="Out", status=Announcement.Status.PUBLISHED, published_at=timezone.now()
        )
        # Regional body (REQ-048): Coast Spinners sits in its region; Amina runs it too.
        self.coast.country, self.coast.region = "KE", "Mombasa"
        self.coast.save(update_fields=["country", "region"])
        self.body = Organization.objects.create(
            name="Coast Region TT", town="Mombasa", country="KE", region="Mombasa", kind="regional_body"
        )
        Membership.objects.create(organization=self.body, user=self.amina).roles.add(
            seed_roles(self.body)[RoleKey.ADMIN]
        )

        # Coast's representatives at the body: one for each thing either side can do to one.
        def sent(user, status="pending"):
            return Representative.objects.create(
                body=self.body, sender=self.coast, user=user, status=status, nominated_by=self.amina
            )

        self.rep_to_withdraw = sent(self.grace)
        self.rep_to_accept = sent(self.amina)
        self.rep_to_decline = sent(self.chiku)
        self.rep_to_remove = sent(self.daudi, "accepted")
        self.agenda_item = AgendaItem.objects.create(
            organization=self.body, title="MARK-AGENDA", starts_on="2027-01-10", ends_on="2027-01-10"
        )
        self.draft_article = Article.objects.create(
            organization=self.body, title="MARK-ARTICLE-DRAFT", body="x"
        )
        self.article = Article.objects.create(
            organization=self.body,
            title="MARK-ARTICLE-PUB",
            body="x",
            status=Article.Status.PUBLISHED,
            published_at=timezone.now(),
        )
        now = timezone.now()
        later = {"starts_at": now + timedelta(days=2), "ends_at": now + timedelta(days=2, hours=2)}

        def meeting(title, invite=(), **extra):
            made = Meeting.objects.create(organization=self.coast, title=title, **{**later, **extra})
            for user in invite:
                MeetingInvitee.objects.create(meeting=made, user=user)
            return made

        self.draft_meeting = meeting("MARK-MEETING-DRAFT", audience=Meeting.Audience.MEMBERS)
        self.meeting_to_publish = meeting("To publish", audience=Meeting.Audience.MEMBERS)
        self.meeting_to_cancel = meeting("To cancel", [self.baraka], status=Meeting.Status.PUBLISHED)
        self.running_meeting = meeting(
            "MARK-MEETING-RUNNING",
            [self.baraka],
            status=Meeting.Status.PUBLISHED,
            starts_at=now - timedelta(minutes=10),
            ends_at=now + timedelta(hours=2),
        )
        over = {"status": Meeting.Status.PUBLISHED, "starts_at": now - timedelta(hours=3)}
        over["ends_at"] = now - timedelta(hours=1)
        rule = {"applies_to": "absent", "penalty": "MARK-PENALTY-RULE", "amount_minor": 5000}
        self.ended_meeting = meeting("Ended", [self.baraka], rules=[rule], **over)
        penalized = meeting("Penalized", [self.baraka], rules=[rule], **over)
        self.penalty = MeetingPenalty.objects.create(
            invitee=penalized.invitees.get(), applies_to="absent", penalty="MARK-PENALTY", amount_minor=5000
        )
        self.minuted_meeting = meeting(
            "Minuted", [self.baraka], minutes="MARK-MINUTES-DRAFT", minutes_status="draft", **over
        )
        self.approved_meeting = meeting(
            "Approved", [self.baraka], minutes="MARK-MINUTES-OUT", minutes_status="approved", **over
        )
        self.action_item = ActionItem.objects.create(
            meeting=self.approved_meeting, description="MARK-ACTION", owner=self.amina
        )
        MinutesAmendment.objects.create(
            meeting=self.approved_meeting, text="MARK-AMENDMENT", created_by=self.amina
        )
        question = {"id": "aaaaaaaaaaaa", "kind": "long_text", "text": "What should change?"}
        question = {**question, "help": "", "required": False, "choices": []}
        sections = [{"id": "bbbbbbbbbbbb", "title": "", "description": "", "questions": [question]}]

        def form(title, **extra):
            made = FeedbackForm.objects.create(
                organization=self.coast, tournament=self.published, title=title, sections=sections, **extra
            )
            made.guests.add(self.baraka)
            return made

        self.form_draft = form("MARK-FORM-DRAFT")
        self.form_to_send = form("To send", to_entrants=False)
        open_now = {
            "status": "sent",
            "opens_at": now - timedelta(days=1),
            "closes_at": now + timedelta(days=3),
        }
        self.form_sent = form("Sent form", intro="MARK-FORM-SENT", anonymous=True, **open_now)
        FeedbackRecipient.objects.create(form=self.form_sent, user=self.baraka, answered=True)
        FeedbackResponse.objects.create(
            form=self.form_sent,
            owner_key=feedback.owner_key(self.form_sent, self.baraka),
            answers={"aaaaaaaaaaaa": "MARK-FEEDBACK-ANSWER"},
        )
        soon = timezone.localdate() + timedelta(days=30)
        slots = [{"id": "cccccccccccc", "label": "Team", "places": 4}]

        def squad(title, **extra):
            return Squad.objects.create(
                organization=self.coast, title=title, starts_on=soon, ends_on=soon, slots=slots, **extra
            )

        self.squad_draft = squad("MARK-SQUAD-DRAFT")
        self.squad_to_publish = squad("To publish squad")
        self.squad_out = squad("Away squad", notes="MARK-SQUAD-NOTES", status=Squad.Status.PUBLISHED)
        self.squad_place = SquadPlace.objects.create(
            squad=self.squad_out,
            slot="cccccccccccc",
            user=self.baraka,
            recommended=False,
            override_reason="MARK-SQUAD-REASON",
        )
        past = timezone.localdate() - timedelta(days=4)
        squad_past = Squad.objects.create(
            organization=self.coast,
            title="Past squad",
            starts_on=past,
            ends_on=past,
            slots=slots,
            status=Squad.Status.PUBLISHED,
        )
        self.squad_place_past = SquadPlace.objects.create(
            squad=squad_past, slot="cccccccccccc", user=self.faith, status=SquadPlace.Status.ACCEPTED
        )

        def penalty(member, what, **extra):
            return AbsencePenalty.objects.create(
                organization=self.coast,
                member=member,
                applies_to="training",
                source_id=uuid.uuid4(),
                what=what,
                happened_on=past,
                kind="warning",
                **extra,
            )

        decided = {"status": "issued", "decided_at": timezone.now()}
        self.penalty_proposed = penalty(self.faith, "MARK-ABSENCE-PROPOSED")
        self.penalty_to_waive = penalty(self.faith, "To waive")
        self.penalty_issued = penalty(self.baraka, "MARK-ABSENCE", **decided)
        self.penalty_appealed = penalty(
            self.baraka, "Appealed", appeal="pending", appeal_text="MARK-APPEAL", **decided
        )
        self.source_unused = ExternalSource.objects.create(organization=self.coast, name="MARK-SOURCE")
        used = ExternalSource.objects.create(organization=self.coast, name="MARK-SOURCE-USED")
        self.external_income = ExternalIncome.objects.create(
            organization=self.coast,
            source=used,
            description="MARK-EXTERNAL-INCOME",
            amount_minor=250000,
            received_on=timezone.localdate(),
            request_key=uuid.uuid4(),
        )
        this_year = timezone.localdate().year

        def report(back, **extra):
            return AnnualReport.objects.create(
                organization=self.coast,
                period_start=f"{this_year - back}-01-01",
                period_end=f"{this_year - back}-12-31",
                **extra,
            )

        frozen = {"period_start": "x", "period_end": "y", "currencies": []}
        self.report_draft = report(1, narrative="MARK-REPORT-DRAFT")
        self.report_to_publish = report(2)
        self.report_out = report(
            3, narrative="MARK-REPORT-OUT", status="published", snapshot=frozen, published_at=timezone.now()
        )
        self.meeting_document = MeetingDocument.objects.create(
            meeting=self.approved_meeting,
            title="MARK-MEETING-PAPER",
            file=Attachment.store(
                owner=self.amina,
                purpose=Attachment.Purpose.MEETING_DOCUMENT,
                content=PDF,
                content_type="application/pdf",
            ),
        )
        nyali_cup = Tournament.objects.create(
            id=NYALI_CUP,
            organization=self.nyali,
            name="Nyali Open",
            starts_on="2026-12-12",
            ends_on="2026-12-12",
            timezone="Africa/Nairobi",
            status=Tournament.Status.PUBLISHED,
        )
        nyali_league = Tournament.objects.create(
            organization=self.nyali,
            name="Nyali League",
            starts_on="2026-12-19",
            ends_on="2026-12-19",
            timezone="Africa/Nairobi",
            status=nyali_cup.status,
        )
        self.offer = Sponsorship.objects.create(
            sponsor=self.coast, tournament=nyali_league, amount_minor=500000, conditions="MARK-SPONSOR-TERMS"
        )
        self.offer_to_accept = Sponsorship.objects.create(
            sponsor=self.nyali, tournament=self.published, amount_minor=100000
        )
        self.document = TournamentDocument.objects.create(
            tournament=self.draft,
            title="Prospectus",
            file=Attachment.store(
                owner=self.amina,
                purpose=Attachment.Purpose.TOURNAMENT_DOCUMENT,
                content=PDF,
                content_type="application/pdf",
            ),
        )
        self.stream = LiveStream.objects.create(
            tournament=self.published, url="https://fb.watch/coast", platform=LiveStream.Platform.FACEBOOK
        )
        self.offer_to_decline = Sponsorship.objects.create(
            sponsor=self.body, tournament=self.published, amount_minor=1
        )

        # Guests of Coast Spinners (REQ-003): one invited (Imani), two with claims waiting for staff.
        self.guest = guests.create(self.coast, "Kassim Guest", self.amina)
        self.guest_invitation = GuestInvitation.objects.create(
            guest=self.guest, email=self.imani.email, invited_by=self.amina
        )

        # A guest invited by phone, whose link only its holder can use.
        _, self.guest_link = guests.invite(
            guests.create(self.coast, "Linked Guest", self.amina), "", self.amina, phone="+254700000009"
        )

        def waiting_claim(name):
            guest = guests.create(self.coast, name, self.amina)
            invitation = GuestInvitation.objects.create(
                # The address staff typed; the claim only shows staff what they already knew.
                guest=guest,
                email="kazi.typed@else.example",
                invited_by=self.amina,
                status="accepted",
            )
            return GuestClaim.objects.create(
                guest=guest, invitation=invitation, claimant=self.daudi, status="conflict", clashes=["x"]
            )

        self.claim_to_retry = waiting_claim("Retry Guest")
        self.claim_to_reject = waiting_claim("Reject Guest")

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
            "match-note-detail": self.match_note.id,
            "me-admin-nomination-accept": self.nomination.id,
            "me-admin-nomination-decline": self.nomination.id,
            "me-invitation-accept": self.invitation.id,
            "me-invitation-decline": self.invitation.id,
            "me-guest-invitation-accept": self.guest_invitation.id,
            "me-guest-invitation-decline": self.guest_invitation.id,
            "organization-guest-detail": self.guest.user_id,
            "organization-guest-invite": self.guest.user_id,
            "organization-guest-revoke-invitation": self.guest.user_id,
            "organization-guest-claim-retry": self.claim_to_retry.id,
            "organization-guest-claim-reject": self.claim_to_reject.id,
            "me-membership-leave": self.baraka_membership.id,
            "me-membership-fields": self.baraka_membership.id,
            "my-drill-detail": self.baraka_drill.id,
            "training-plan-detail": self.baraka_plan.id,
            "training-plan-item": self.baraka_item.id,
            "tournament-ceremony-award": self.award.id,
            "tournament-announcement": self.news_draft.id,
            "tournament-announcement-publish": self.news_to_publish.id,
            "tournament-announcement-amend": self.news_out.id,
            "tournament-announcement-card": self.news_out.id,
            "tournament-announcement-pdf": self.news_out.id,
            "tournament-ceremony-award-present": self.award_to_present.id,
            "organization-agenda-item": self.agenda_item.id,
            "organization-article": self.article.id,
            "organization-article-publish": self.draft_article.id,
            "organization-meeting": self.draft_meeting.id,
            "organization-meeting-publish": self.meeting_to_publish.id,
            "organization-meeting-cancel": self.meeting_to_cancel.id,
            "organization-meeting-minutes": self.running_meeting.id,
            "organization-meeting-minutes-approve": self.minuted_meeting.id,
            "organization-meeting-minutes-amendments": self.approved_meeting.id,
            "organization-meeting-action-item": self.approved_meeting.id,
            "organization-meeting-documents": self.running_meeting.id,
            "organization-meeting-document": self.approved_meeting.id,
            "organization-meeting-answer": self.running_meeting.id,
            "organization-meeting-check-in": self.running_meeting.id,
            "organization-meeting-attendance": self.running_meeting.id,
            "organization-meeting-penalties": self.ended_meeting.id,
            "organization-meeting-penalty": self.penalty.invitee.meeting_id,
            "organization-sponsorship-withdraw": self.offer.id,
            "tournament-sponsorship-accept": self.offer_to_accept.id,
            "tournament-sponsorship-decline": self.offer_to_decline.id,
            "tournament-stream": self.stream.id,
            "tournament-document": self.document.id,
            "tournament-stream-report": self.stream.id,
            "coach": self.kito.id,
            "coach-slots": self.kito.id,
            "my-coach-comment": self.coach_note.id,
            "my-coaching-accept": self.coaching.id,
            "my-coaching-decline": self.coaching.id,
            "my-coaching-end": self.coaching.id,
            "my-trainee": self.coaching.id,
            "my-trainee-plans": self.coaching.id,
            "my-trainee-plan": self.coaching.id,
            "my-trainee-plan-recommendations": self.coaching.id,
            "my-trainee-plan-item": self.baraka_item.id,
            "my-trainee-comments": self.coaching.id,
            "my-booking-confirm": self.booking.id,
            "my-booking-decline": self.booking.id,
            "my-booking-cancel": self.booking.id,
            "organization-drill": self.club_drill.id,
            "drill-library-detail": self.club_drill.id,
            "training-plan-recommendations": self.baraka_plan.id,
            "organization-training-plan": self.spare_club_plan.id,
            "organization-training-plan-recommendations": self.club_plan.id,
            "organization-training-plan-item": self.club_item.id,
            # Faith's, because the staff checks remove Baraka before they reach this route.
            "organization-member-fields": self.faith_membership.id,
            "organization-member-field": self.staff_field.id,
            "organization-representative-withdraw": self.rep_to_withdraw.id,
            "organization-representative-accept": self.rep_to_accept.id,
            "organization-representative-decline": self.rep_to_decline.id,
            "organization-representative-remove": self.rep_to_remove.id,
            "organization-committee-position": self.position.id,
            "organization-committee-position-values": self.position.id,
            "organization-committee-position-holder": self.vacant_position.id,
            "organization-committee-position-retire": self.retiring_position.id,
            "organization-committee-field": self.committee_field.id,
            "organization-committee-field-retire": self.committee_field.id,
            "organization-committee-field-restore": self.committee_field.id,
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
            "organization-venue-hours": self.venue.id,
            "my-table-booking-cancel": self.booking.id,
            "organization-booking-approve": self.booking.id,
            "organization-booking-reject": self.booking_to_reject.id,
            "organization-booking-cancel": self.booking_to_cancel.id,
            "organization-venue-pass": self.day_pass.id,
            "organization-venue-visit-reverse": self.walk_in.id,
            "facility-detail": self.venue.id,
            "facility-schedule": self.venue.id,
            "open-session-join": self.club_session.id,
            "open-session-leave": self.club_session.id,
            "tournament-detail": self.deletable.id,
            "tournament-publish": self.spare_draft.id,
            "tournament-request-approval": self.regional_draft.id,
            "tournament-reject-approval": self.regional_draft.id,
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
            "tournament-event-entry-self-check-in": self.baraka_entry.id,
            "tournament-event-entry-undo-check-in": self.faith_entry.id,
            "tournament-event-entry-withdraw": self.baraka_entry.id,
            "tournament-event-match": self.preview_match_id,
            "tournament-event-match-recap": self.preview_match_id,
            "tournament-event-match-card": self.preview_match_id,
            "tournament-event-match-lineup": self.tie.id,
            "tournament-event-match-lineup-reset": self.tie.id,
            "tournament-event-match-umpire": self.scored_match.id,
            "tournament-event-match-dispatch": self.to_dispatch.id,
            "tournament-event-match-recall": self.on_table.id,
            "tournament-event-match-call": self.called.id,
            "tournament-event-match-report": self.called.id,
            "tournament-event-match-move": self.called.id,
            "tournament-event-match-result": self.to_decide.id,
            "tournament-event-match-result-correct": self.decided.id,
            "tournament-correction-resolve": self.resolution.id,
            "scorecard-detail": self.scorecard.id,
            "scorecard-events": self.scorecard.id,
            "scorecard-confirm": self.scorecard.id,
            "scorecard-next": self.scorecard.id,
            "scorecard-device": self.scorecard.id,
            "scorecard-conflicts": self.scorecard.id,
            "tournament-scoring-conflict-resolve": self.conflict.id,
            "organization-detail": self.coast.id,
            "organization-profile": self.coast.id,
            "player-detail": self.baraka.id,
            "player-ratings": self.baraka.id,
            "tournament-schedule-session": self.session.id,
            "organization-club-session": self.club_session.id,
            "organization-activity": self.activity.id,
            "soda-game-detail": self.soda.id,
            "notification-read": self.alert.id,
            "organization-charge-waive": self.charge.id,
            "organization-payment-allocate": self.payment.id,
            "organization-payment-reverse": self.payment_to_reverse.id,
            "organization-campaign": self.campaign.id,
            "organization-campaign-close": self.campaign_to_close.id,
            "organization-campaign-terms": self.campaign.id,
            "organization-campaign-dues": self.campaign.id,
            "organization-campaign-remind": self.campaign.id,
            "organization-expense-reverse": self.expense_to_reverse.id,
            "organization-expense-receipt": self.expense.id,
            "organization-welfare-project": self.welfare.id,
            "organization-welfare-project-hide": self.welfare_to_hide.id,
            "organization-welfare-project-close": self.welfare_to_close.id,
            "organization-welfare-project-due": self.welfare_to_due.id,
            "organization-welfare-contributions": self.welfare.id,
            "organization-welfare-contribution-reverse": self.welfare.id,
            "organization-welfare-expenses": self.welfare.id,
            "organization-external-event": self.external.id,
            "organization-external-event-live": self.external.id,
            "external-event-approve": self.external.id,
            "external-event-reject": self.external.id,
            "external-event-remove-link": self.external.id,
            "external-event-report": self.external.id,
            "soda-game-accept": self.soda.id,
            "soda-game-counter": self.soda.id,
            "soda-game-decline": self.soda.id,
            "soda-game-withdraw": self.soda.id,
            "soda-game-result": self.soda.id,
            "soda-game-confirm": self.soda.id,
            "soda-game-dispute": self.soda.id,
            "soda-game-settle": self.soda.id,
            "soda-game-share": self.soda.id,
            "organization-activity-publish": self.activity_draft.id,
            "organization-activity-cancel": self.activity_to_cancel.id,
            "organization-activity-rsvp": self.activity.id,
            "organization-activity-check-in": self.activity.id,
            "organization-activity-attendance": self.activity_running.id,
            "organization-feedback-form": self.form_draft.id,
            "organization-annual-report": self.report_draft.id,
            "organization-external-source": self.source_unused.id,
            "organization-external-income-reverse": self.external_income.id,
            "organization-annual-report-publish": self.report_to_publish.id,
            "organization-annual-report-amend": self.report_out.id,
            "organization-annual-report-csv": self.report_out.id,
            "organization-annual-report-pdf": self.report_out.id,
            "organization-squad": self.squad_draft.id,
            "organization-squad-publish": self.squad_to_publish.id,
            "organization-squad-recommendation": self.squad_out.id,
            "organization-squad-places": self.squad_out.id,
            "organization-squad-place-remove": self.squad_out.id,
            "organization-squad-place-attendance": self.squad_place_past.squad_id,
            "organization-absence-penalty-issue": self.penalty_proposed.id,
            "organization-absence-penalty-waive": self.penalty_to_waive.id,
            "organization-absence-penalty-appeal": self.penalty_appealed.id,
            "my-absence-penalty-appeal": self.penalty_issued.id,
            "my-squad-place-accept": self.squad_place.id,
            "my-squad-place-decline": self.squad_place.id,
            "organization-feedback-form-send": self.form_to_send.id,
            "organization-feedback-form-closing": self.form_sent.id,
            "organization-feedback-form-totals": self.form_sent.id,
            "organization-feedback-form-export": self.form_sent.id,
            "feedback-form": self.form_sent.id,
            "organization-activity-cost-share": self.activity_to_share.id,
            "organization-activity-attendees": self.activity.id,
            "organization-activity-invitees": self.activity.id,
            "organization-club-session-cancel": self.session_to_cancel.id,
            "organization-club-session-location": self.club_session.id,
            "my-session-invitation-check-in": self.session_invitation.id,
            "my-session-invitation-apologise": self.session_invitation.id,
            "organization-club-session-invitation": self.session_invitation.id,
            "my-session-invitation-accept": self.session_invitation.id,
            "my-session-invitation-decline": self.session_invitation.id,
        }
        found = {}
        if "code" in names:
            found["code"] = "KE"
        if "token" in names:
            found["token"] = self.guest_link
        if "organization_pk" in names:
            found["organization_pk"] = self.coast.id
        if "pk" in names:
            found["pk"] = pk[name]
        if "venue_pk" in names:
            found["venue_pk"] = self.venue.id
        if "session_pk" in names:
            found["session_pk"] = self.club_session.id
        if "contribution_pk" in names:
            found["contribution_pk"] = self.welfare_contribution.id
        if "device_pk" in names:
            found["device_pk"] = self.push_device.id
        if "penalty_pk" in names:
            found["penalty_pk"] = self.penalty.id
        if "action_pk" in names:
            found["action_pk"] = self.action_item.id
        if "place_pk" in names:
            past = name == "organization-squad-place-attendance"
            found["place_pk"] = (self.squad_place_past if past else self.squad_place).id
        if "document_pk" in names:
            found["document_pk"] = self.meeting_document.id
        if "plan_pk" in names:
            club = name.startswith("organization-training-plan")
            found["plan_pk"] = (self.club_plan if club else self.baraka_plan).id
        if name.startswith(("tournament-ceremony", "tournament-announcement")):
            found["tournament_pk"] = self.published.id
            return found
        if name == "tournament-review":
            found["tournament_pk"] = self.reviewed.id
            return found
        if name.startswith(("organization-region", "organization-agenda", "organization-article")):
            found["organization_pk"] = self.body.id
        if name in BODY_SIDE:
            found["organization_pk"] = self.body.id
        if name.startswith(("tournament-sponsor", "tournament-stream")):
            found["tournament_pk"] = self.published.id
            return found
        if "coaching_pk" in names:
            found["coaching_pk"] = self.coaching.id
        if "table_pk" in names:
            found["table_pk"] = self.table.id
        if name == "tournament-umpire":
            found["tournament_pk"], found["user_pk"] = self.scored_cup.id, UMPIRE_USER
            return found
        if name.startswith("tournament-order-of-play"):
            found["tournament_pk"] = self.order_cup.id
            if "user_pk" in names:
                found["user_pk"] = self.order_player.id
            if "match_pk" in names:
                found["match_pk"] = Match.objects.get(draw__event__tournament=self.order_cup).id
            return found
        if name in ("tournament-table-block", "tournament-table-unblock", "tournament-table-umpire"):
            found["tournament_pk"] = self.scored_cup.id
            return found
        if name in (
            "tournament-check-in-desk",
            "tournament-match-day-log",
            "tournament-umpires",
            "tournament-umpire-candidates",
        ):
            found["tournament_pk"] = self.scored_cup.id
            return found
        control = (
            "tournament-event-match-call",
            "tournament-event-match-report",
            "tournament-event-match-move",
        )
        if name in control:
            found["event_pk"], found["tournament_pk"] = self.control_cup.event.id, self.control_cup.id
            return found
        if name.startswith("tournament-schedule"):
            found["tournament_pk"] = self.planned_cup.id
            if "number" in names:
                found["number"] = 1
            return found
        whole = ("tournament-tables", "tournament-reservations")
        if name.startswith(("tournament-scoring", "tournament-dispatch")) or name in whole:
            found["tournament_pk"] = self.scored_cup.id
            return found
        if name in ("tournament-event-match-dispatch", "tournament-event-match-recall"):
            cup = self.dispatch_cup if name.endswith("dispatch") else self.recall_cup
            found["event_pk"], found["tournament_pk"] = cup.event.id, cup.id
            return found
        results = {
            "tournament-event-match-result": self.result_cup,
            "tournament-event-match-result-correct": self.corrected_cup,
        }
        if name in results:
            found["event_pk"], found["tournament_pk"] = results[name].event.id, results[name].id
            return found
        if name in ("tournament-corrections", "tournament-correction-resolve"):
            found["tournament_pk"] = self.question_cup.id
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
            "guests": sorted(
                User.objects.filter(guest__isnull=False).values_list(
                    "display_name", "is_active", "guest__claimed_by"
                )
            ),
            "guest_invitations": sorted(GuestInvitation.objects.values_list("email", "status")),
            "guest_claims": sorted(GuestClaim.objects.values_list("guest__user__display_name", "status")),
            "admin_handovers": sorted(AdminHandover.objects.values_list("to_user__email", "status")),
            "join_requests": sorted(JoinRequest.objects.values_list("user__email", "status")),
            "matches": sorted(PersonalMatch.objects.values_list("id", "label", "notes")),
            "match_notes": sorted(MatchNote.objects.values_list("id", "observations", "goals")),
            "avatars": sorted(PlayerProfile.objects.values_list("user__email", "avatar_id")),
            "member_fields": sorted(
                MemberField.objects.values_list("label", "visibility", "required", "retired_at")
            ),
            "member_field_values": sorted(MemberFieldValue.objects.values_list("field__label", "value")),
            "committee_positions": sorted(
                CommitteePosition.objects.values_list("name", "order", "retired_at", "grants_role")
            ),
            "committee_holders": sorted(
                PositionHolder.objects.values_list("position__name", "membership_id", "ended_at")
            ),
            "committee_fields": sorted(CommitteeField.objects.values_list("label", "retired_at")),
            "committee_values": sorted(CommitteeFieldValue.objects.values_list("field__label", "value")),
            "venues": sorted(Venue.objects.values_list("name", "town", "active", "profile")),
            "opening_hours": sorted(OpeningHour.objects.values_list("venue__name", "weekday", "opens")),
            "passes": sorted(Pass.objects.values_list("name", "amount_minor", "active")),
            "table_bookings": sorted(TableBooking.objects.values_list("note", "status", "fee_minor")),
            "visits": sorted(
                (str(v), w, r is None)
                for v, w, r in Visit.objects.values_list("id", "walk_in_name", "reversed_at")
            ),
            "equipment": sorted(Equipment.objects.values_list("user__email", "blade")),
            "drills": sorted(Drill.objects.values_list("title", "focus", "repetitions")),
            "training_plans": sorted(TrainingPlan.objects.values_list("title", "goal")),
            "activities": sorted(Activity.objects.values_list("title", "status", "place")),
            "soda": sorted(
                (str(i), st, a, b)
                for i, st, a, b in Challenge.objects.values_list(
                    "id", "status", "challenger_shares", "challenged_shares"
                )
            ),
            "external_events": sorted(
                ExternalEvent.objects.values_list(
                    "name", "review", "status", "venue", "live_url", "marked_live"
                )
            ),
            "link_reports": LinkReport.objects.count(),
            "alerts": sorted(
                (str(r), t, a is None)
                for r, t, a in Notification.objects.values_list("recipient_id", "title", "read_at")
            ),
            "alert_preferences": sorted(Preference.objects.values_list("user_id", "category")),
            "push_devices": sorted(
                (str(u), e) for u, e in PushSubscription.objects.values_list("user_id", "endpoint")
            ),
            "charges": sorted((c.purpose, c.amount_minor, c.waived_at is None) for c in Charge.objects.all()),
            "payments": sorted(
                (p.reference, p.amount_minor, p.reversed_at is None) for p in Payment.objects.all()
            ),
            "allocations": Allocation.objects.count(),
            "campaigns": sorted(
                (c.title, c.amount_minor, c.closed_at is None) for c in Campaign.objects.all()
            ),
            "campaign_terms": sorted(CampaignMember.objects.values_list("amount_minor", "waived")),
            "welfare_projects": sorted(
                (w.title, w.show_contributors, w.hidden_at is None, w.closed_at is None)
                for w in WelfareProject.objects.all()
            ),
            "welfare_gifts": WelfareContribution.objects.count(),
            "expenses": sorted(
                (e.description, e.amount_minor, e.reversed_at is None, str(e.receipt_id))
                for e in Expense.objects.all()
            ),
            "soda_policies": sorted(
                Policy.objects.values_list("organization__name", "games_enabled", "stakes_enabled")
            ),
            "rsvps": sorted(
                Rsvp.objects.values_list("activity__title", "user_id", "answer", "attended", "checked_in_at")
            ),
            "club_sessions": sorted(ClubSession.objects.values_list("title", "status", "notes")),
            "session_invitations": sorted(
                SessionInvitation.objects.values_list(
                    "session__title", "user_id", "status", "attended", "apology_reason"
                )
            ),
            "session_places": sorted(
                ClubSession.objects.values_list("title", "location_label", "location_latitude"), key=str
            ),
            "training_rules": sorted(TrainingRules.objects.values_list("radius_m", "location_label")),
            "plan_items": sorted(PlanItem.objects.values_list("title", "completed_at")),
            "ceremonies": sorted(Ceremony.objects.values_list("location", "status")),
            "reviews": sorted(TournamentReview.objects.values_list("went_well", "went_wrong")),
            "awards": sorted(Award.objects.values_list("title", "order", "prize", "presented_at")),
            "agenda": sorted(AgendaItem.objects.values_list("title", "starts_on")),
            "articles": sorted(Article.objects.values_list("title", "summary", "status")),
            "meetings": sorted(
                Meeting.objects.values_list("title", "status", "location", "minutes", "minutes_status")
            ),
            "action_items": sorted(ActionItem.objects.values_list("description", "status")),
            "amendments": MinutesAmendment.objects.count(),
            "meeting_documents": sorted(MeetingDocument.objects.values_list("title", "item")),
            "feedback_forms": sorted(FeedbackForm.objects.values_list("title", "status", "closes_at")),
            "feedback_recipients": FeedbackRecipient.objects.count(),
            "annual_reports": sorted(
                AnnualReport.objects.values_list("period_end", "version", "status", "narrative", "public"),
                key=str,
            ),
            "finance_settings": FinanceSettings.objects.count(),
            "external_sources": sorted(ExternalSource.objects.values_list("name", "active")),
            "external_income": sorted(
                ExternalIncome.objects.values_list("description", "amount_minor", "reversed_at"), key=str
            ),
            "squads": sorted(Squad.objects.values_list("title", "status", "notes")),
            "squad_places": sorted(
                SquadPlace.objects.values_list("user__email", "status", "attended"), key=str
            ),
            "absence_rules": AbsenceRule.objects.count(),
            "absence_penalties": sorted(
                AbsencePenalty.objects.values_list("what", "status", "appeal", "appeal_text")
            ),
            "feedback_responses": sorted(FeedbackResponse.objects.values_list("answers", flat=True), key=str),
            "meeting_invitees": sorted(
                MeetingInvitee.objects.values_list("user__email", "answer", "checked_in_at", "attendance")
            ),
            "meeting_penalties": sorted(
                MeetingPenalty.objects.values_list(
                    "invitee__user__email", "penalty", "amount_minor", "status"
                )
            ),
            "sponsorships": sorted(Sponsorship.objects.values_list("amount_minor", "status")),
            "streams": sorted(LiveStream.objects.values_list("url", "title")),
            "stream_reports": sorted(LiveStreamReport.objects.values_list("reporter__email", "reason")),
            "coach_profiles": sorted(
                CoachProfile.objects.values_list("user__email", "headline", "accepting")
            ),
            "coachings": sorted(Coaching.objects.values_list("id", "status")),
            "representatives": sorted(Representative.objects.values_list("id", "status")),
            "caps": sorted(Organization.objects.values_list("id", "representative_cap")),
            "bookings": sorted(Booking.objects.values_list("id", "status", "starts_at")),
            "coach_notes": sorted(MatchComment.objects.values_list("id", "body")),
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
            "results": sorted(OfficialResult.objects.values_list("match_id", "version", "current")),
            "resolutions": sorted(Resolution.objects.values_list("id", "resolved_at")),
            "decided": sorted(Match.objects.values_list("id", "status", "winner_id")),
            "outbox": Job.objects.count(),
            "lineups": Lineup.objects.count(),
            "rubbers": Rubber.objects.count(),
            "draws": sorted(DrawVersion.objects.values_list("event__name", "version", "status", "rng_seed")),
            "plans": sorted(Match.objects.values_list("id", "draft_at", "scheduled_at")),
            "schedule_versions": ScheduleVersion.objects.count(),
            "sessions": sorted(ScheduleSession.objects.values_list("id", "name")),
        }


@pytest.fixture
def world(db):
    return World()


def call(client, method: str, name: str, url: str):
    body = BODIES.get((name, method), {})
    kind = "multipart" if name in MULTIPART else "json"
    return getattr(client, method)(url, body() if callable(body) else body, format=kind)


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


# Viewers who hold a staff route's permission through their role, so the refusal test skips them there.
# Grace sits on the committee, whose template role sees the finances.
# The committee's template role also runs club activities.
ALSO_STAFF = {
    "organization-facility-takings": {"grace"},
    **{
        name: {"grace"}
        for name in [
            "organization-charges",
            "organization-charge-waive",
            "organization-payments",
            "organization-payment-allocate",
            "organization-payment-reverse",
            "organization-balances",
            "organization-campaigns",
            "organization-campaign",
            "organization-campaign-close",
            "organization-campaign-terms",
            "organization-campaign-dues",
            "organization-campaign-remind",
            "organization-expenses",
            "organization-expense-reverse",
            "organization-expense-receipt",
            "organization-finance-summary",
            "organization-finance-settings",
            "organization-external-sources",
            "organization-external-source",
            "organization-external-income",
            "organization-external-income-reverse",
            "organization-income-totals",
            "organization-annual-reports",
            "organization-annual-report",
            "organization-annual-report-publish",
            "organization-annual-report-amend",
            "organization-welfare-projects",
            "organization-welfare-project",
            "organization-welfare-project-hide",
            "organization-welfare-project-close",
            "organization-welfare-project-due",
            "organization-welfare-contributions",
            "organization-welfare-contribution-reverse",
            "organization-welfare-expenses",
        ]
    },
    # ...and announcements, which include submitting external events.
    **{
        name: {"grace"}
        for name in (
            "organization-external-events",
            "organization-external-event",
            "organization-external-event-live",
            "organization-announcements",
        )
    },
    **{
        name: {"grace"}
        for name in (
            "organization-activities",
            "organization-activity",
            "organization-activity-publish",
            "organization-activity-cancel",
            "organization-activity-invitees",
            "organization-activity-attendance",
            "organization-activity-cost-share",
        )
    },
}


@pytest.mark.parametrize("who", ["baraka", "faith", "chiku", "daudi", "grace", "hamisi", "operator"])
def test_staff_routes_refuse_members_other_clubs_and_outsiders(world, who):
    before = world.state()
    client = logged_in(world.viewers[who])
    for name, methods, names in ROUTES:
        for method in methods:
            if ACCESS[name][method] != STAFF or who in ALSO_STAFF.get(name, ()):
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
    asked = imani.get("/api/v1/me/guest-invitations/").json()["results"]
    assert [i["id"] for i in asked] == [str(world.guest_invitation.id)]
    claimed = imani.post(
        reverse("me-guest-invitation-accept", kwargs={"pk": world.guest_invitation.id}), {}, format="json"
    )
    assert claimed.json()["status"] == "merged"

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
    """The bodies of every GET route (with searches that would match the private markers). `user=None`
    reads them signed out."""
    client = logged_in(user) if user else BrowserClient()
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
        # A PDF is Latin-1, not UTF-8: read it leniently, the markers are plain ASCII either way.
        served.append(response.content.decode(errors="replace"))
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
        "MARK-BARAKA-OBSERVATION": {"baraka"},
        "MARK-SESSION-NOTE": {"amina", "baraka", "faith"},  # training staff and the two invited
        "MARK-ACTIVITY-PRIVATE": {"amina", "baraka", "faith", "grace"},  # the club's members
        "MARK-SODA-MESSAGE": {"baraka"},
        "MARK-ALERT": {"baraka"},
        # Members see each campaign's totals and spending (REQ-024); receipts stay with finance staff.
        "MARK-CAMPAIGN": {"amina", "baraka", "faith", "grace"},
        "MARK-EXPENSE": {"amina", "baraka", "faith", "grace"},
        "MARK-WELFARE": {"amina", "baraka", "faith", "grace"},  # the project's audience
        "MARK-WELFARE-DESC": {"amina", "baraka", "faith", "grace"},
        "MARK-WELFARE-REF": {"amina", "faith", "grace"},  # the giver's own payment, and staff
        str(world.receipt.id): {"amina", "grace"},
        "MARK-CHARGE": {"amina", "faith", "grace"},  # the member and finance staff
        "MARK-PAYMENT-REF": {"amina", "faith", "grace"},
        "MARK-EXTERNAL-PENDING": {
            "amina",
            "baraka",
            "faith",
            "grace",
        },  # the submitting club, pre-review  # the two players (Imani isn't a viewer here)
        "MARK-SODA-STAKE": set(),  # stakes stay hidden from everyone while the policy gate is off
        "MARK-ACTIVITY-DRAFT": {"amina", "grace"},  # those who run activities
        "MARK-EVENT-NAMED": {"amina", "grace", "chiku"},  # the person named and those who run activities
        "MARK-FORM-DRAFT": {"amina"},  # the host's competition staff
        "MARK-SOURCE": {"amina", "grace"},  # the club's outside sources and income: finance staff
        "MARK-EXTERNAL-INCOME": {"amina", "grace"},
        "MARK-REPORT-DRAFT": {
            "amina",
            "grace",
        },  # a draft report: finance staff (the committee reads finances)
        "MARK-REPORT-OUT": {"amina", "baraka", "faith", "grace"},  # published, not public: the members
        "MARK-SQUAD-DRAFT": {"amina"},  # a draft squad is for the selectors
        "MARK-ABSENCE-PROPOSED": {"amina"},  # undecided: governance staff only, not yet the member
        "MARK-ABSENCE": {"amina", "baraka"},  # issued: the member too
        "MARK-APPEAL": {"amina", "baraka"},
        "MARK-SQUAD-NOTES": {"amina", "baraka"},  # and a published one for the players picked
        "MARK-SQUAD-REASON": {"amina"},  # why someone was picked out of turn: selectors only
        "MARK-FORM-SENT": {"amina", "baraka"},  # and whoever was asked
        "MARK-FEEDBACK-ANSWER": {"amina", "baraka"},  # the answer as text, never with a name
        "MARK-WALK-IN": {"amina"},  # the facility's staff only
        "MARK-TABLE-BOOKING": {"amina", "baraka"},  # the requester and the venue's staff
        "MARK-VISIT-REF": {"amina"},  # the club's training staff and the invited member
        "MARK-APOLOGY": {"amina", "faith"},  # the member who sent it and the training staff
        "MARK-TRAINING-PLACE": {"amina", "baraka", "faith", "grace"},  # where the club trains, by name
        "4.043911": {"amina"},  # its coordinates: training staff only
        str(world.baraka_avatar.id): {"baraka"},
        str(world.match.id): {"baraka"},
        "MARK-FAITH-BIO": {"faith"},  # unpublished
        "MARK-BARAKA-BLADE": {"baraka"},
        "MARK-BARAKA-DRILL": {"baraka"},
        "MARK-BARAKA-PLAN": {"baraka"},
        "MARK-BARAKA-ITEM": {"baraka"},
        "MARK-AWARD-DRAFT": {"amina"},  # a draft ceremony isn't anyone's honour yet
        "MARK-ANNOUNCEMENT-DRAFT": {"amina"},  # a draft announcement is the host's staff's
        "MARK-CEREMONY-PLACE": {"amina"},
        "MARK-REVIEW": {"amina"},  # the host's competition staff
        "MARK-REVIEW-ACTION": {"amina"},
        "MARK-AGENDA": {"amina", "baraka", "faith", "grace"},
        "MARK-ARTICLE-PUB": {"amina", "baraka", "faith", "grace"},
        "MARK-ARTICLE-DRAFT": {"amina"},
        "MARK-MEETING-DRAFT": {"amina"},
        "MARK-MEETING-RUNNING": {"amina", "baraka"},
        "MARK-PENALTY-RULE": {"amina", "baraka"},  # the meeting's invitees and staff
        "MARK-PENALTY": {"amina", "baraka"},  # the penalized invitee and staff
        "MARK-MINUTES-DRAFT": {"amina"},  # draft minutes are for whoever writes and approves them
        "MARK-MINUTES-OUT": {"amina", "baraka"},  # approved: the invitees too
        "MARK-ACTION": {"amina", "baraka"},
        "MARK-AMENDMENT": {"amina", "baraka"},
        "MARK-MEETING-PAPER": {"amina", "baraka"},
        "MARK-SPONSOR-TERMS": {"amina"},
        "MARK-COACH-NOTE": {"baraka"},
        "MARK-COACHING-MESSAGE": {"baraka"},
        "MARK-BOOKING-NOTE": {"baraka"},
        "MARK-CLUB-DRILL": {"amina", "baraka", "faith", "grace"},
        "MARK-CLUB-PLAN": {"amina", "baraka", "faith", "grace"},
        "MARK-CLUB-ITEM": {"amina", "baraka", "faith", "grace"},
        # Controls: a listed player's published detail and picture reach every signed-in viewer, which
        # shows the crawl really reads the pages where a leak would appear.
        "MARK-FAITH-STYLE": set(world.viewers),
        str(world.faith_avatar.id): set(world.viewers),
        "Tea committee": {"amina"},  # role names are for staff, also as what a committee seat grants
        # The committee and its history are for members; staff-only committee fields for governance staff.
        "MARK-POSITION": {"amina", "baraka", "faith", "grace"},
        "MARK-CFIELD-MEMBER": {"amina", "baraka", "faith", "grace"},
        "MARK-CVALUE-MEMBER": {"amina", "baraka", "faith", "grace"},
        "MARK-CFIELD-STAFF": {"amina"},
        "MARK-CVALUE-STAFF": {"amina"},
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
    # Signed out (TASK-035): the published tournament and its accepted entries, and nothing the directory
    # or a club keeps for signed-in players (Faith's listed style and photo are the control).
    public = {"Published Cup", "Grace Achieng"}
    served = everything_served_to(world, None)
    for marker in allowed:
        if marker in public:
            assert marker in served, f"signed out should see {marker}"
        else:
            assert marker not in served, f"{marker} leaked to a signed-out caller"


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
        "country",
        "region",
        "directions",
        "latitude",
        "longitude",
        "description",
        "kind",
        "timezone",
    }
    profile = viewer.get(f"/api/v1/organizations/{world.coast.id}/profile/").json()
    assert set(profile) == {
        "id",
        "name",
        "kind",
        "country",
        "region",
        "town",
        "directions",
        "latitude",
        "longitude",
        "description",
        "timezone",
        "venues",
        "training_hours",
        "upcoming_tournaments",
    }
    assert {"id", "name", "starts_on", "ends_on", "scope", "status", "venue_name"} >= {
        key for tournament in profile["upcoming_tournaments"] for key in tournament
    }
    cup = viewer.get(f"/api/v1/tournaments/{world.published.id}/").json()
    assert set(cup) == {
        "id",
        "organization",
        "organizer",
        "presented_as",
        "venue",
        "name",
        "description",
        "cover",
        "documents",
        "starts_on",
        "ends_on",
        "timezone",
        "scope",
        "approval_status",
        "registration_fee",
        "schedule_notice_minutes",
        "status",
        "published_at",
        "started_at",
        "completed_at",
        "cancelled_at",
        "cancel_reason",
        "events",
    }
    assert set(cup["organization"]) == {"id", "name", "town", "country", "region"}
    assert set(cup["organizer"]) == {"name", "kind", "label"}
    # A place's directions and coordinates are public, like its address: they help players find it.
    assert set(cup["venue"]) == {"id", "name", "town", "address", "directions", "latitude", "longitude"}

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
