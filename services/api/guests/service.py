"""Guests and their claims (REQ-003): create, invite, accept, and staff resolution of clashes."""

import uuid

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from accounts.models import GUEST_EMAIL_DOMAIN, User
from core.exceptions import ApiException
from organizations.models import Organization

from . import merge
from .models import Guest, GuestClaim, GuestClaimEvent, GuestInvitation


def create(organization: Organization, display_name: str, actor) -> Guest:
    """A player with no account yet: no address of theirs and no password, so nobody can sign in as it."""
    user = User(
        email=f"guest-{uuid.uuid4().hex}@{GUEST_EMAIL_DOMAIN}",
        display_name=display_name,
    )
    user.set_unusable_password()
    user.save()
    return Guest.objects.create(user=user, organization=organization, created_by=actor)


def still_a_guest(guest: Guest) -> None:
    if guest.claimed_by_id:
        raise ApiException("guest_claimed", "This guest already belongs to a player's account.", 409)


def invite(guest: Guest, email: str, actor) -> GuestInvitation:
    """Ask the person behind the guest to claim it. A new invitation replaces any still open."""
    still_a_guest(guest)
    if guest.claims.filter(status=GuestClaim.Status.CONFLICT).exists():
        raise ApiException(
            "claim_open", "A claim for this guest is waiting for you to resolve it first.", 409
        )
    now = timezone.now()
    guest.invitations.filter(status=GuestInvitation.Status.PENDING).update(
        status=GuestInvitation.Status.REVOKED, decided_at=now
    )
    invitation = GuestInvitation.objects.create(guest=guest, email=email.strip().lower(), invited_by=actor)
    transaction.on_commit(lambda: _send_invitation(invitation))
    return invitation


def _send_invitation(invitation: GuestInvitation) -> None:
    """Sent whether or not the address has an account, so inviting never reveals who is registered."""
    guest = invitation.guest
    club = guest.organization.name
    inviter = invitation.invited_by.display_name if invitation.invited_by else "Club staff"
    try:
        send_mail(
            f"Claim your matches at {club} on Coast TT",
            f'{inviter} at {club} entered you on Coast TT as "{guest.user.display_name}" before you had '
            "an account. Claim that player to add their entries and results to your own account.\n\n"
            f"Log in with this email address to accept or decline: {settings.FRONTEND_URL}/profile/claims\n"
            f"New to Coast TT? Sign up with this address first: {settings.FRONTEND_URL}/signup\n\n"
            f"The invitation expires on {invitation.expires_at:%d %b %Y}. "
            "If this isn't you, ignore this email.",
            None,
            [invitation.email],
        )
    except Exception:  # the invitation stands: staff can send it again
        pass


def revoke(invitation: GuestInvitation) -> None:
    if invitation.status != GuestInvitation.Status.PENDING:
        raise ApiException("already_decided", "This invitation has already been answered.", 409)
    invitation.status = GuestInvitation.Status.REVOKED
    invitation.decided_at = timezone.now()
    invitation.save(update_fields=["status", "decided_at"])


def _try_merge(claim: GuestClaim, actor, action: str, note: str = "") -> GuestClaim:
    guest = claim.guest
    try:
        merge.move(guest.user, claim.claimant)
    except merge.Clash as clash:
        claim.status = GuestClaim.Status.CONFLICT
        claim.clashes = clash.clashes
        claim.save(update_fields=["status", "clashes"])
        GuestClaimEvent.objects.create(
            claim=claim,
            actor=actor,
            action=action if action == GuestClaimEvent.Action.RETRIED else GuestClaimEvent.Action.CONFLICT,
            note=note or "; ".join(clash.clashes),
        )
        return claim
    now = timezone.now()
    claim.status = GuestClaim.Status.MERGED
    claim.clashes = []
    claim.resolved_at = now if action == GuestClaimEvent.Action.RETRIED else None
    claim.save(update_fields=["status", "clashes", "resolved_at"])
    if action == GuestClaimEvent.Action.RETRIED:
        GuestClaimEvent.objects.create(claim=claim, actor=actor, action=action, note=note)
    GuestClaimEvent.objects.create(claim=claim, actor=actor, action=GuestClaimEvent.Action.MERGED)
    guest.claimed_by = claim.claimant
    guest.claimed_at = now
    guest.save(update_fields=["claimed_by", "claimed_at"])
    # The guest user stays as a record of what it became; nobody can sign in as it or enter it again.
    User.objects.filter(pk=guest.user_id).update(is_active=False)
    return claim


def accept(invitation: GuestInvitation, claimant) -> GuestClaim:
    """The invitee takes the guest. The invitation is used up whatever happens next: merged now, or
    waiting for staff because something clashes."""
    if claimant.pk == invitation.guest.user_id or not claimant.email_verified_at:
        raise ApiException("not_allowed", "Only a verified account can claim a guest.", 403)
    still_a_guest(invitation.guest)
    invitation.status = GuestInvitation.Status.ACCEPTED
    invitation.decided_at = timezone.now()
    invitation.save(update_fields=["status", "decided_at"])
    claim = GuestClaim.objects.create(
        guest=invitation.guest, invitation=invitation, claimant=claimant, status=GuestClaim.Status.CONFLICT
    )
    GuestClaimEvent.objects.create(claim=claim, actor=claimant, action=GuestClaimEvent.Action.ACCEPTED)
    return _try_merge(claim, claimant, GuestClaimEvent.Action.MERGED)


def decline(invitation: GuestInvitation) -> None:
    invitation.status = GuestInvitation.Status.DECLINED
    invitation.decided_at = timezone.now()
    invitation.save(update_fields=["status", "decided_at"])


def _open(claim: GuestClaim) -> None:
    if claim.status != GuestClaim.Status.CONFLICT:
        raise ApiException("claim_settled", "This claim has already been settled.", 409)


def retry(claim: GuestClaim, actor, note: str) -> GuestClaim:
    """Staff have dealt with what clashed (withdrawn the duplicate entry, say): try the move again."""
    _open(claim)
    return _try_merge(claim, actor, GuestClaimEvent.Action.RETRIED, note)


def reject(claim: GuestClaim, actor, note: str) -> GuestClaim:
    """Staff decide the guest and the account are not one player. The guest stays as it was."""
    _open(claim)
    claim.status = GuestClaim.Status.REJECTED
    claim.resolved_at = timezone.now()
    claim.save(update_fields=["status", "resolved_at"])
    GuestClaimEvent.objects.create(
        claim=claim, actor=actor, action=GuestClaimEvent.Action.REJECTED, note=note
    )
    return claim
