from django.conf import settings
from django.core.mail import send_mail

from .models import Invitation


def send_invitation_email(invitation: Invitation) -> None:
    """Sent whether or not the address has an account, so inviting never reveals who is registered. An
    invited player gets it at their own verified address, if they have one; either way the invitation
    waits for them in the app."""
    if invitation.invitee is not None:
        invitee = invitation.invitee
        to = invitee.email if invitee.email and invitee.email_verified_at else ""
    else:
        to = invitation.email
    if not to:
        return
    inviter = invitation.invited_by.display_name if invitation.invited_by else "A club admin"
    send_mail(
        f"You're invited to join {invitation.organization.name} on Coast TT",
        f"{inviter} invited you to join {invitation.organization.name} ({invitation.organization.town}).\n\n"
        f"Log in with this email address to accept or decline: {settings.FRONTEND_URL}/club/invitations\n"
        f"New to Coast TT? Sign up with this address first: {settings.FRONTEND_URL}/signup\n\n"
        f"The invitation expires on {invitation.expires_at:%d %b %Y}. "
        "If you don't want to join, ignore this email.",
        None,
        [to],
    )
