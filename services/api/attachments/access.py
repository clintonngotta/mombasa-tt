"""Who may read an attachment (REQ-020). Checked every time a signed link is issued."""

from profiles.models import listed_profiles

from .models import Attachment


def can_read(user, attachment: Attachment) -> bool:
    if not user.is_authenticated or not user.is_active:
        return False
    if attachment.purpose == Attachment.Purpose.RECEIPT:
        # Decided by the finance permission alone, even for whoever uploaded it.
        from finance.summaries import can_read_receipt

        return can_read_receipt(user, attachment)
    if attachment.purpose in (Attachment.Purpose.TOURNAMENT_COVER, Attachment.Purpose.TOURNAMENT_DOCUMENT):
        # Whoever may see the tournament it belongs to.
        from competitions.views import sees_tournament

        return sees_tournament(user, attachment)
    if attachment.owner_id == user.id:
        return True
    if attachment.purpose == Attachment.Purpose.AVATAR:
        # Only while it is the current photo of a listed player.
        return listed_profiles().filter(avatar=attachment).exists()
    return False
