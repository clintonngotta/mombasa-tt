import hashlib
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import Storage, storages
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver


class PrivateStorage(Storage):
    """settings.STORAGES["attachments"], looked up on each call so the configured backend is always the
    one used. Nothing in it has a public URL; files leave only through a signed link
    (attachments.signing)."""

    @property
    def backend(self) -> Storage:
        return storages["attachments"]

    def open(self, name, mode="rb"):
        return self.backend.open(name, mode)

    def save(self, name, content, max_length=None):
        return self.backend.save(name, content, max_length=max_length)

    def delete(self, name):
        self.backend.delete(name)

    def exists(self, name):
        return self.backend.exists(name)

    def size(self, name):
        return self.backend.size(name)


def attachment_storage() -> PrivateStorage:
    return PrivateStorage()


def storage_name(attachment, filename: str) -> str:
    # Named by id, never by what the uploader called the file.
    return f"{attachment.purpose}/{attachment.id}{attachment.EXTENSIONS[attachment.content_type]}"


class Attachment(models.Model):
    """A private uploaded file (REQ-020). Who may read one is decided per purpose in attachments.access."""

    class Purpose(models.TextChoices):
        AVATAR = "avatar"
        RECEIPT = "receipt"  # an expense's receipt (REQ-024), for finance staff only
        # A tournament's cover picture and its documents (REQ-007): whoever may see the tournament.
        TOURNAMENT_COVER = "tournament_cover"
        TOURNAMENT_DOCUMENT = "tournament_document"

    EXTENSIONS = {"image/webp": ".webp", "application/pdf": ".pdf"}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attachments")
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    file = models.FileField(storage=attachment_storage, upload_to=storage_name, max_length=120)
    content_type = models.CharField(max_length=60)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)  # checked against restored objects (deployment.md)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.purpose} {self.id}"

    @classmethod
    def store(cls, *, owner, purpose: str, content: bytes, content_type: str) -> "Attachment":
        """Save already-validated bytes as a new attachment."""
        attachment = cls(
            owner=owner,
            purpose=purpose,
            content_type=content_type,
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        attachment.file.save("upload", ContentFile(content), save=False)
        try:
            attachment.save()
        except BaseException:
            attachment.discard_file()
            raise
        return attachment

    def discard_file(self) -> None:
        """Remove the stored file of an attachment whose row was never committed, so a failed or rolled
        back save leaves nothing behind in storage."""
        self.file.storage.delete(self.file.name)


@receiver(post_delete, sender=Attachment)
def delete_stored_file(sender, instance, **kwargs):
    """Remove the stored file once the row is really gone (also on cascades from the owner)."""
    storage, name = instance.file.storage, instance.file.name
    if name:
        transaction.on_commit(lambda: storage.delete(name))
