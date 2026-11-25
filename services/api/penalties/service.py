"""Finding absences, proposing penalties, and issuing, waiving and appealing them (REQ-054)."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from competitions.models import Entry, EntryPlayer, Tournament
from core.exceptions import ApiException
from finance import ledger
from finance.models import Charge
from notifications.models import Category
from notifications.service import notify
from organizations.models import Membership, Organization
from squads.models import Squad, SquadPlace
from training.models import ClubSession, SessionInvitation

from .models import Absence, AbsencePenalty, AbsenceRule, PenaltyKind

LOOK_BACK_DAYS = 90
MAX_PROPOSALS = 500
P = AbsencePenalty.Status


def _absences(organization: Organization, rule: AbsenceRule, since) -> list[dict]:
    """The absences of one kind since `since`, each {member, source_id, what, happened_on}: only active
    members of the organization, only what has ended."""
    today = timezone.localdate()
    members = set(
        Membership.objects.active().filter(organization=organization).values_list("user_id", flat=True)
    )
    found = []
    if rule.applies_to == Absence.TRAINING:
        missed = SessionInvitation.objects.filter(
            session__organization=organization,
            session__status=ClubSession.Status.SCHEDULED,
            session__ends_at__lt=timezone.now(),
            session__starts_at__date__gte=since,
            attended=False,
            user__in=members,
        ).select_related("session")
        # Accepted and stayed away; or, when an apology doesn't excuse, apologised and stayed away.
        missed = missed.filter(status=SessionInvitation.Status.ACCEPTED) | (
            missed.none() if rule.apology_excuses else missed.filter(apologised_at__isnull=False)
        )
        for row in missed[:MAX_PROPOSALS]:
            found.append(
                {
                    "member": row.user_id,
                    "source_id": row.pk,
                    "what": row.session.title,
                    "happened_on": timezone.localdate(row.session.starts_at),
                }
            )
    elif rule.applies_to == Absence.TOURNAMENT:
        absent = EntryPlayer.objects.filter(
            entry__event__tournament__organization=organization,
            entry__event__tournament__status__in=[Tournament.Status.COMPLETED, Tournament.Status.IN_PROGRESS],
            entry__event__tournament__ends_on__lt=today,
            entry__event__tournament__ends_on__gte=since,
            entry__status=Entry.Status.ACCEPTED,
            entry__checked_in_at__isnull=True,
            checked_in_at__isnull=True,
            user__in=members,
        ).select_related("entry__event__tournament")
        for row in absent[:MAX_PROPOSALS]:
            tournament = row.entry.event.tournament
            found.append(
                {
                    "member": row.user_id,
                    "source_id": row.entry_id,
                    "what": f"{tournament.name}: {row.entry.event.name}"[:160],
                    "happened_on": tournament.starts_on,
                }
            )
    else:
        absent = SquadPlace.objects.filter(
            squad__organization=organization,
            squad__status=Squad.Status.PUBLISHED,
            squad__ends_on__lt=today,
            squad__ends_on__gte=since,
            status=SquadPlace.Status.ACCEPTED,
            attended=False,
            user__in=members,
        ).select_related("squad")
        for row in absent[:MAX_PROPOSALS]:
            found.append(
                {
                    "member": row.user_id,
                    "source_id": row.pk,
                    "what": row.squad.title,
                    "happened_on": row.squad.starts_on,
                }
            )
    return found


@transaction.atomic
def propose(organization: Organization) -> int:
    """Make a proposed penalty for each absence of the last 90 days that an active rule covers and that
    has none yet. Running it again adds nothing twice. Returns how many were new."""
    since = timezone.localdate() - timedelta(days=LOOK_BACK_DAYS)
    made = 0
    for rule in AbsenceRule.objects.filter(organization=organization, active=True):
        for absence in _absences(organization, rule, since):
            _, created = AbsencePenalty.objects.get_or_create(
                organization=organization,
                applies_to=rule.applies_to,
                source_id=absence["source_id"],
                member_id=absence["member"],
                defaults={
                    "what": absence["what"],
                    "happened_on": absence["happened_on"],
                    "kind": rule.kind,
                    "suspension_events": rule.suspension_events
                    if rule.kind == PenaltyKind.SUSPENSION
                    else None,
                    "points": rule.points if rule.kind == PenaltyKind.POINTS else None,
                    "fine_minor": rule.fine_minor,
                    "currency": rule.currency,
                },
            )
            made += created
    return made


def _locked(penalty: AbsencePenalty) -> AbsencePenalty:
    return (
        AbsencePenalty.objects.select_for_update(of=("self",))
        .select_related("organization")
        .get(pk=penalty.pk)
    )


def _tell(penalty: AbsencePenalty, title: str) -> None:
    notify(
        [penalty.member_id],
        Category.PENALTY,
        title,
        subject=f"absence-penalty:{penalty.pk}",
        version=f"{penalty.status}:{penalty.appeal}",
        body=penalty.what,
        link="/penalties",
        organization=penalty.organization,
    )


@transaction.atomic
def issue(penalty: AbsencePenalty, actor, reason: str) -> AbsencePenalty:
    penalty = _locked(penalty)
    if penalty.status != P.PROPOSED:
        raise ApiException("already_decided", "This penalty was already decided.", 409)
    penalty.status, penalty.reason = P.ISSUED, reason
    penalty.decided_by, penalty.decided_at = actor, timezone.now()
    if penalty.fine_minor:
        penalty.charge = Charge.objects.create(
            organization=penalty.organization,
            member_id=penalty.member_id,
            kind=Charge.Kind.OTHER,
            purpose=f"Penalty: {penalty.what}"[:120],
            amount_minor=penalty.fine_minor,
            currency=penalty.currency,
            source_id=penalty.pk,
            created_by=actor,
        )
    penalty.save()
    _tell(penalty, "A penalty was issued to you")
    return penalty


def _waive(penalty: AbsencePenalty, actor, reason: str) -> None:
    penalty.status, penalty.reason = P.WAIVED, reason
    penalty.decided_by, penalty.decided_at = actor, timezone.now()
    if penalty.charge_id:
        ledger.waive(penalty.charge, actor, reason)  # the fine is no longer owed


@transaction.atomic
def waive(penalty: AbsencePenalty, actor, reason: str) -> AbsencePenalty:
    penalty = _locked(penalty)
    if penalty.status == P.WAIVED:
        raise ApiException("already_decided", "This penalty was already waived.", 409)
    was_issued = penalty.status == P.ISSUED
    _waive(penalty, actor, reason)
    if penalty.appeal == AbsencePenalty.Appeal.PENDING:
        penalty.appeal, penalty.appeal_decided_by = AbsencePenalty.Appeal.UPHELD, actor
    penalty.save()
    if was_issued:
        _tell(penalty, "A penalty of yours was waived")
    return penalty


@transaction.atomic
def appeal(penalty: AbsencePenalty, text: str) -> AbsencePenalty:
    penalty = _locked(penalty)
    if penalty.status != P.ISSUED:
        raise ApiException("not_issued", "Only an issued penalty can be appealed.", 409)
    if penalty.appeal:
        raise ApiException("already_appealed", "A penalty can be appealed once.", 409)
    penalty.appeal, penalty.appeal_text = AbsencePenalty.Appeal.PENDING, text
    penalty.appealed_at = timezone.now()
    penalty.save(update_fields=["appeal", "appeal_text", "appealed_at"])
    return penalty


@transaction.atomic
def decide_appeal(penalty: AbsencePenalty, actor, *, upheld: bool, note: str) -> AbsencePenalty:
    penalty = _locked(penalty)
    if penalty.appeal != AbsencePenalty.Appeal.PENDING:
        raise ApiException("no_appeal", "There is no appeal waiting on this penalty.", 409)
    penalty.appeal = AbsencePenalty.Appeal.UPHELD if upheld else AbsencePenalty.Appeal.REJECTED
    penalty.appeal_note, penalty.appeal_decided_by = note, actor
    if upheld:
        _waive(penalty, actor, note or "Appeal upheld")
    penalty.save()
    _tell(penalty, "Your appeal succeeded" if upheld else "Your appeal was turned down")
    return penalty


def suspended(organization: Organization, user_ids) -> set:
    """Members serving a suspension from selection: an issued suspension of N events lasts until the
    organization has published N squads since it was issued."""
    serving = set()
    penalties = AbsencePenalty.objects.filter(
        organization=organization, member__in=user_ids, status=P.ISSUED, kind=PenaltyKind.SUSPENSION
    )
    for penalty in penalties:
        since = Squad.objects.filter(
            organization=organization, status=Squad.Status.PUBLISHED, published_at__gt=penalty.decided_at
        ).count()
        if since < (penalty.suspension_events or 0):
            serving.add(penalty.member_id)
    return serving
