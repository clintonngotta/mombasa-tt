"""Who may read an attachment (REQ-020). Checked every time a signed link is issued."""

from profiles.models import listed_profiles

from .models import Attachment


def can_read(user, attachment: Attachment) -> bool:
    if not user.is_authenticated or not user.is_active:
        return False
    if attachment.owner_id == user.id:
        return True
    if attachment.purpose == Attachment.Purpose.AVATAR:
        # Only while it is the current photo of a listed player.
        return listed_profiles().filter(avatar=attachment).exists()
    return False
