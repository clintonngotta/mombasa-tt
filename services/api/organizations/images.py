"""Pictures an organization shows of itself (REQ-058): a club, a team or a facility.

Holders of roles.manage upload them, at most MAX_IMAGES; any signed-in player sees them with the
organization's profile. Each is re-encoded like every image (bounded size, no metadata), stored privately
and served through signed links (attachments.signing).
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from attachments.images import MAX_UPLOAD_BYTES, OUTPUT_CONTENT_TYPE, normalize_image
from attachments.models import Attachment
from attachments.serializers import AttachmentLinkSerializer
from core.exceptions import ApiException

from .access import lock_organization, require_permission
from .models import MAX_IMAGES, Organization, OrganizationImage
from .permissions import Permission

IMAGE_SIDE = 1600
SLACK = 64 * 1024  # multipart framing around the file


class OrganizationImageSerializer(serializers.ModelSerializer):
    file = AttachmentLinkSerializer(source="file_id", read_only=True)

    class Meta:
        model = OrganizationImage
        fields = ["id", "caption", "file", "created_at"]
        read_only_fields = fields


class OrganizationImagesSerializer(serializers.Serializer):
    limit = serializers.IntegerField(help_text="The most pictures an organization may show.")
    images = OrganizationImageSerializer(many=True)


class OrganizationImageUploadSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="A JPEG, PNG or WebP image under 5 MB.")
    caption = serializers.CharField(max_length=120, required=False, allow_blank=True, trim_whitespace=True)


def reply(organization: Organization, code=status.HTTP_200_OK) -> Response:
    shown = {"limit": MAX_IMAGES, "images": organization.images.all()[:MAX_IMAGES]}
    return Response(OrganizationImagesSerializer(shown).data, status=code)


class OrganizationImagesView(APIView):
    """GET /organizations/{id}/images/: any signed-in player, as the profile is. POST adds a picture:
    holders of roles.manage."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    @property
    def throttle_scope(self):
        # Uploads are limited per person; looking at the pictures is not.
        return "uploads" if self.request.method == "POST" else None

    @extend_schema(responses={200: OrganizationImagesSerializer})
    def get(self, request, organization_pk):
        return reply(get_object_or_404(Organization, pk=organization_pk))

    @extend_schema(
        request={"multipart/form-data": OrganizationImageUploadSerializer},
        responses={201: OrganizationImagesSerializer},
    )
    def post(self, request, organization_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        require_permission(request.user, organization, Permission.ROLES_MANAGE)
        if int(request.META.get("CONTENT_LENGTH") or 0) > MAX_UPLOAD_BYTES + SLACK:
            raise ValidationError({"file": "Choose an image under 5 MB."})
        body = OrganizationImageUploadSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        content = normalize_image(body.validated_data["file"], max_side=IMAGE_SIDE)
        new = None
        try:
            with transaction.atomic():
                # Locked, and checked again inside: two uploads at once can't pass the limit together,
                # and a role lost meanwhile no longer counts.
                organization = lock_organization(organization)
                require_permission(request.user, organization, Permission.ROLES_MANAGE)
                if organization.images.count() >= MAX_IMAGES:
                    raise ApiException(
                        "image_limit",
                        f"You can show up to {MAX_IMAGES} pictures. Remove one to add another.",
                        409,
                    )
                new = Attachment.store(
                    owner=request.user,
                    purpose=Attachment.Purpose.ORGANIZATION_IMAGE,
                    content=content,
                    content_type=OUTPUT_CONTENT_TYPE,
                )
                OrganizationImage.objects.create(
                    organization=organization, file=new, caption=body.validated_data.get("caption", "")
                )
        except BaseException:
            if new is not None:
                new.discard_file()
            raise
        return reply(organization, status.HTTP_201_CREATED)


class OrganizationImageView(APIView):
    """DELETE /organizations/{id}/images/{image}/ removes a picture and its file: roles.manage."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: OrganizationImagesSerializer})
    def delete(self, request, organization_pk, image_pk):
        organization = get_object_or_404(Organization, pk=organization_pk)
        with transaction.atomic():
            require_permission(request.user, organization, Permission.ROLES_MANAGE)
            image = get_object_or_404(OrganizationImage, pk=image_pk, organization=organization)
            image.file.delete()  # cascades to the picture's row; the stored file goes on commit
        return reply(organization)
