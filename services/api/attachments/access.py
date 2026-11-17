"""Who may read an attachment (REQ-020). Checked every time a signed link is issued."""

from profiles.models import PlayerProfile

from .models import Attachment


def can_read(user, attachment: Attachment) -> bool:
    if not user.is_authenticated or not user.is_active:
        return False
    if attachment.owner_id == user.id:
        return True
    if attachment.purpose == Attachment.Purpose.AVATAR:
        return listed_avatar_ids([attachment.id]) == {attachment.id}
    return False


def listed_avatar_ids(attachment_ids) -> set:
    """Of these attachments, the ones that are the current avatar of a player listed in the directory."""
    return set(
        PlayerProfile.objects.filter(
            avatar_id__in=attachment_ids, directory_opt_in=True, user__is_active=True
        ).values_list("avatar_id", flat=True)
    )
