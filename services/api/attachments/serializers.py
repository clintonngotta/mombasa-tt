from rest_framework import serializers

from . import signing


class AttachmentLinkSerializer(serializers.Serializer):
    """A short-lived link to an attachment's content. `url` is a path on the API origin.

    Serializing one issues the link, so only use it where the viewer has already been allowed to read
    the attachment. Give it the attachment id."""

    id = serializers.UUIDField()
    url = serializers.CharField()
    expires_at = serializers.DateTimeField()

    def to_representation(self, attachment_id):
        return super().to_representation(signing.link(attachment_id))
