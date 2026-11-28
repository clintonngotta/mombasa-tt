"""Guests and their claims (REQ-003): create, invite, accept, and staff resolution of clashes."""

import hashlib
import secrets
import uuid

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from accounts import emails
from accounts.models import GUEST_EMAIL_DOMAIN, User
from core.exceptions import ApiException
from organizations.models import Organization
from profiles.models import PlayerProfile

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


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def join_link(token: str) -> str:
    return f"{settings.FRONTEND_URL}/join/{token}"


def by_token(token: str, lock: bool = False) -> GuestInvitation | None:
    """The open invitation this link belongs to, or None (unknown, used, revoked or lapsed)."""
    found = GuestInvitation.objects.select_related("guest__user", "guest__organization", "invited_by")
    if lock:
        found = found.select_for_update(of=("self",))
    invitation = found.filter(token_hash=_hash(token)).first() if token else None
    return invitation if invitation and invitation.is_open else None


MEMBER = "member"  # the guest was added as a club member, not (only) entered in a tournament


def _replace_open(guest: Guest) -> None:
    """Before a new invitation: the guest must still be one, with no clash waiting for staff, and any
    invitation still open is withdrawn (one open invitation per guest)."""
    still_a_guest(guest)
    if guest.claims.filter(status=GuestClaim.Status.CONFLICT).exists():
        raise ApiException(
            "claim_open", "A claim for this guest is waiting for you to resolve it first.", 409
        )
    guest.invitations.filter(status=GuestInvitation.Status.PENDING).update(
        status=GuestInvitation.Status.REVOKED, decided_at=timezone.now()
    )


def invite(
    guest: Guest, email: str, actor, phone: str = "", purpose: str = "", send: bool = True
) -> tuple[GuestInvitation, str]:
    """Ask the person behind the guest to claim it, by email, phone or both. A new invitation replaces
    any still open. `purpose` MEMBER words the email for someone added to the club; `send` False makes
    the link without emailing it. Returns the invitation and its link's secret, which is shown to staff
    once (to share by WhatsApp or SMS) and never stored."""
    _replace_open(guest)
    token = secrets.token_urlsafe(32)
    invitation = GuestInvitation.objects.create(
        guest=guest,
        email=(email or "").strip().lower(),
        phone=phone or "",
        invited_by=actor,
        token_hash=_hash(token),
    )
    if invitation.email and send:
        transaction.on_commit(lambda: _send_invitation(invitation, token, purpose))
    return invitation, token


def new_link(guest: Guest, actor) -> tuple[GuestInvitation, str]:
    """A fresh link for staff to share, when the last one was lost, used up or lapsed. It goes to the
    email and phone staff last invited, if any (an invitation to a player found in the directory has
    neither), and nothing is emailed: staff share it themselves. The old link stops working."""
    last = (
        guest.invitations.filter(invitee__isnull=True)
        .exclude(email="", phone="")
        .order_by("-created_at")
        .first()
    )
    return invite(guest, last.email if last else "", actor, last.phone if last else "", send=False)


def link_player(guest: Guest, player: User, actor) -> GuestInvitation:
    """Ask a player already on Coast TT whether they are this guest. It waits in their inbox, and they
    get an email at their own verified address if they have one. Nothing moves until they accept, and
    staff learn nothing about their account from it."""
    if player.pk == guest.user_id:
        raise ApiException("not_allowed", "Choose the player this guest is.", 400)
    _replace_open(guest)
    invitation = GuestInvitation.objects.create(guest=guest, invitee=player, invited_by=actor)
    transaction.on_commit(lambda: _send_player_notice(invitation))
    return invitation


def _send_player_notice(invitation: GuestInvitation) -> None:
    player = invitation.invitee
    if not (player.email and player.email_verified_at):
        return
    guest = invitation.guest
    club = guest.organization.name
    inviter = invitation.invited_by.display_name if invitation.invited_by else "Club staff"
    try:
        send_mail(
            f"Are these your matches at {club}?",
            f'{inviter} at {club} entered a player as "{guest.user.display_name}" before they were on '
            "Coast TT, and thinks it was you. If it was, claim them under Profile, Matches entered for "
            "you, and the entries and results become yours.\n\n"
            f"Open: {settings.FRONTEND_URL}/profile/claims\n\n"
            f"The request expires on {invitation.expires_at:%d %b %Y}. If it wasn't you, decline it there "
            "or ignore this email.",
            None,
            [player.email],
        )
    except Exception:  # the request still waits in the app
        pass


def _send_invitation(invitation: GuestInvitation, token: str, purpose: str = "") -> None:
    """Sent whether or not the address has an account, so inviting never reveals who is registered."""
    guest = invitation.guest
    club = guest.organization.name
    inviter = invitation.invited_by.display_name if invitation.invited_by else "Club staff"
    if purpose == MEMBER:
        subject = f"You've been added to {club} on Coast TT"
        body = (
            f'{inviter} added you to {club} on Coast TT as "{guest.user.display_name}". Open the link to '
            "set your password and sign in.\n\n"
            f"Set your password here: {join_link(token)}\n"
            "Already on Coast TT? The same link lets you log in and add the membership to your account.\n\n"
        )
    else:
        subject = f"Claim your matches at {club} on Coast TT"
        body = (
            f'{inviter} at {club} entered you on Coast TT as "{guest.user.display_name}" before you had '
            "an account. Join to see your entries and results, and check your details.\n\n"
            f"Join or claim them here: {join_link(token)}\n"
            "Already on Coast TT? The same link lets you log in and add them to your account.\n\n"
        )
    try:
        send_mail(
            subject,
            body + f"The invitation expires on {invitation.expires_at:%d %b %Y}. "
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
    if claimant.pk == invitation.guest.user_id or not claimant.is_verified:
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


class Taken(Exception):
    """The email or phone the invitee chose already belongs to another account."""

    def __init__(self, field: str):
        super().__init__(field)
        self.field = field


def join(invitation: GuestInvitation, details: dict) -> tuple[User, bool]:
    """The invitee has no account yet: the guest becomes their account, so its entries, matches and
    results are theirs with nothing to move. `details`: display_name, password, and email, phone or
    both, and optionally country, region and city.

    The invitation proves whatever it was sent to: an email that matches it is verified, and so is a
    phone that matches it. Anything else must be confirmed first (an email gets a verification link).
    Returns the account and whether it can sign in now."""
    guest = invitation.guest
    still_a_guest(guest)
    user = guest.user
    email, phone = details.get("email") or "", details.get("phone") or ""
    if email and User.objects.filter(email=email).exclude(pk=user.pk).exists():
        raise Taken("email")
    if phone and User.objects.filter(phone=phone).exclude(pk=user.pk).exists():
        raise Taken("phone")
    now = timezone.now()
    user.display_name = details["display_name"]
    if email:
        user.email = email
        user.email_verified_at = now if email == invitation.email else None
    if phone:
        user.phone = phone
        user.phone_verified_at = now if phone == invitation.phone else None
    user.set_password(details["password"])
    user.save()
    if details.get("country"):
        PlayerProfile.objects.update_or_create(
            user=user,
            defaults={"country": details["country"], "region": details["region"], "city": details["city"]},
        )
    invitation.status = GuestInvitation.Status.ACCEPTED
    invitation.decided_at = now
    invitation.save(update_fields=["status", "decided_at"])
    claim = GuestClaim.objects.create(
        guest=guest, invitation=invitation, claimant=user, status=GuestClaim.Status.MERGED
    )
    GuestClaimEvent.objects.create(claim=claim, actor=user, action=GuestClaimEvent.Action.ACCEPTED)
    GuestClaimEvent.objects.create(
        claim=claim, actor=user, action=GuestClaimEvent.Action.MERGED, note="Joined from the invitation"
    )
    guest.claimed_by = user
    guest.claimed_at = now
    guest.save(update_fields=["claimed_by", "claimed_at"])
    if email and not user.is_email_verified:
        transaction.on_commit(lambda: emails.send_verification_email(user))
    return user, user.is_verified
