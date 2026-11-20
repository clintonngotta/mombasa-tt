"""A tournament's cover picture and documents (REQ-007).

The host's competition staff upload them; whoever may see the tournament sees them. The cover is
re-encoded like every image (no metadata); documents must be PDFs. Both are stored privately and served
through signed links (attachments.signing).
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from attachments.documents import MAX_DOCUMENT_BYTES, PDF_CONTENT_TYPE, read_pdf
from attachments.images import MAX_UPLOAD_BYTES, OUTPUT_CONTENT_TYPE, normalize_image
from attachments.models import Attachment
from core.exceptions import ApiException

from .models import MAX_DOCUMENTS, Tournament, TournamentDocument
from .serializers import CoverUploadSerializer, TournamentDocumentUploadSerializer, TournamentSerializer
from .views import reply, staff_tournament

COVER_SIDE = 1600
SLACK = 64 * 1024  # multipart framing around the file


def too_big(request, limit: int) -> bool:
    return int(request.META.get("CONTENT_LENGTH") or 0) > limit + SLACK


def store(request, purpose: str, content: bytes, content_type: str) -> Attachment:
    return Attachment.store(owner=request.user, purpose=purpose, content=content, content_type=content_type)


class TournamentCoverView(APIView):
    """PUT /tournaments/{id}/cover/ sets (or replaces) the cover picture; DELETE removes it."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]
    throttle_scope = "uploads"

    @extend_schema(
        request={"multipart/form-data": CoverUploadSerializer}, responses={200: TournamentSerializer}
    )
    def put(self, request, tournament_pk):
        if too_big(request, MAX_UPLOAD_BYTES):
            raise ValidationError({"file": "Choose an image under 5 MB."})
        body = CoverUploadSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        content = normalize_image(body.validated_data["file"], max_side=COVER_SIDE)
        new = None
        try:
            with transaction.atomic():
                tournament = staff_tournament(request.user, tournament_pk)
                old = tournament.cover
                new = store(request, Attachment.Purpose.TOURNAMENT_COVER, content, OUTPUT_CONTENT_TYPE)
                tournament.cover = new
                tournament.save(update_fields=["cover", "updated_at"])
                if old:
                    old.delete()
        except BaseException:
            if new is not None:
                new.discard_file()
            raise
        return reply(tournament)

    @extend_schema(request=None, responses={200: TournamentSerializer})
    def delete(self, request, tournament_pk):
        with transaction.atomic():
            tournament = staff_tournament(request.user, tournament_pk)
            if tournament.cover:
                old = tournament.cover
                tournament.cover = None
                tournament.save(update_fields=["cover", "updated_at"])
                old.delete()
        return reply(tournament)


class TournamentDocumentsView(APIView):
    """POST /tournaments/{id}/documents/ adds a PDF with a title, such as the prospectus or entry form."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]
    throttle_scope = "uploads"

    @extend_schema(
        request={"multipart/form-data": TournamentDocumentUploadSerializer},
        responses={201: TournamentSerializer},
    )
    def post(self, request, tournament_pk):
        if too_big(request, MAX_DOCUMENT_BYTES):
            raise ValidationError({"file": "Choose a PDF under 10 MB."})
        body = TournamentDocumentUploadSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        content = read_pdf(body.validated_data["file"])
        new = None
        try:
            with transaction.atomic():
                tournament = staff_tournament(request.user, tournament_pk)
                if tournament.documents.count() >= MAX_DOCUMENTS:
                    raise ApiException(
                        "too_many_documents", f"A tournament can have {MAX_DOCUMENTS} documents.", 409
                    )
                new = store(request, Attachment.Purpose.TOURNAMENT_DOCUMENT, content, PDF_CONTENT_TYPE)
                TournamentDocument.objects.create(
                    tournament=tournament, title=body.validated_data["title"], file=new
                )
        except BaseException:
            if new is not None:
                new.discard_file()
            raise
        return reply(tournament, status.HTTP_201_CREATED)


class TournamentDocumentView(APIView):
    """DELETE /tournaments/{id}/documents/{document}/ removes a document and its file."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: TournamentSerializer})
    def delete(self, request, tournament_pk, pk):
        with transaction.atomic():
            tournament: Tournament = staff_tournament(request.user, tournament_pk)
            document = get_object_or_404(TournamentDocument, pk=pk, tournament=tournament)
            document.file.delete()  # cascades to the document
        return reply(tournament)
