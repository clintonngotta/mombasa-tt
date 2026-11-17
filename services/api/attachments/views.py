from django.http import FileResponse, Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import ApiException

from .access import can_read
from .models import Attachment
from .serializers import AttachmentLinkSerializer
from .signing import token_is_valid


class AttachmentLinkView(APIView):
    """Issue a fresh signed link. An attachment the caller may not read answers 404, exactly like one
    that doesn't exist."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: AttachmentLinkSerializer})
    def get(self, request, pk):
        attachment = Attachment.objects.filter(pk=pk).first()
        if attachment is None or not can_read(request.user, attachment):
            raise Http404
        return Response(AttachmentLinkSerializer(attachment.id).data)


class AttachmentContentView(APIView):
    """The file itself. The signed token is the authorization (it was checked when the link was issued),
    so no session is needed and an image tag can load it."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter("token", str, required=True, description="From a signed link")],
        responses={(200, "image/webp"): OpenApiTypes.BINARY},
    )
    def get(self, request, pk):
        if not token_is_valid(request.query_params.get("token", ""), pk):
            raise ApiException("link_expired", "This link has expired or isn't valid.", 403)
        attachment = Attachment.objects.filter(pk=pk).first()
        if attachment is None:
            raise Http404
        try:
            content = attachment.file.open("rb")
        except FileNotFoundError:
            raise Http404 from None
        response = FileResponse(content, content_type=attachment.content_type)
        # Private data: keep it out of shared and service-worker caches, and never let it run as a page.
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response
