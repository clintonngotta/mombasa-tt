"""A meeting's notices, documents and minutes (REQ-046).

Invitees are told when a meeting is published, changed or cancelled, when a penalty is issued to them and
when the minutes are approved. Governance staff or the secretary write the minutes as a draft: the text,
decisions per agenda item, action items and the next meeting's date. Someone with the governance permission
approves them; from then on they never change, and a correction is an amendment kept beside them. Whoever
owns an action item sees it across organizations and marks it done.
"""

from django.db import transaction
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from attachments.documents import MAX_DOCUMENT_BYTES, PDF_CONTENT_TYPE, read_pdf
from attachments.models import Attachment
from competitions.models import Tournament
from core.exceptions import ApiException
from notifications.models import Category
from notifications.service import notify
from organizations.access import effective_permissions
from organizations.models import Membership, Organization
from organizations.permissions import Permission

from .models import (
    MAX_MEETING_DOCUMENTS,
    ActionItem,
    Meeting,
    MeetingDocument,
    MinutesAmendment,
)
from .serializers import (
    ActionItemStatusSerializer,
    AmendmentInputSerializer,
    ApproveMinutesSerializer,
    MeetingDocumentUploadSerializer,
    MeetingSerializer,
    MinutesSerializer,
    MyActionItemSerializer,
)

GOVERNANCE = Permission.GOVERNANCE_MANAGE
SLACK = 64 * 1024  # multipart framing around the file
MAX_OWNER_CHOICES = 500
MAX_MY_ACTION_ITEMS = 100


def link(meeting: Meeting) -> str:
    return f"/meetings/{meeting.organization_id}/{meeting.pk}"


def tell_invitees(meeting: Meeting, title: str, *, subject: str, version, actor=None, also=()) -> None:
    """One notice to each invitee (and `also`), except whoever made the change. Call inside the
    transaction that made it."""
    people = set(meeting.invitees.values_list("user_id", flat=True)) | {pk for pk in also if pk}
    if actor is not None:
        people.discard(actor.pk)
    notify(
        people,
        Category.MEETING,
        title,
        subject=f"{subject}:{meeting.pk}",
        version=version,
        link=link(meeting),
        organization=meeting.organization,
    )


def tournament_names(found_meetings) -> dict:
    """Names of the tournaments the agendas link to, for one query however many meetings are shown."""
    linked = {row.get("tournament") for meeting in found_meetings for row in meeting.agenda}
    linked.discard(None)
    if not linked:
        return {}
    return {str(pk): name for pk, name in Tournament.objects.filter(pk__in=linked).values_list("pk", "name")}


def owner_choices(meeting: Meeting) -> dict:
    """Who an action item can be given to: the invitees and the host's active members, by name."""
    people = dict(meeting.invitees.values_list("user_id", "user__display_name"))
    members = (
        Membership.objects.active()
        .filter(organization=meeting.organization_id)
        .order_by("user__display_name")
        .values_list("user_id", "user__display_name")[:MAX_OWNER_CHOICES]
    )
    people.update(dict(members))
    return dict(sorted(people.items(), key=lambda person: person[1].lower()))


def sees_meeting(user, meeting: Meeting) -> tuple[bool, bool]:
    """(may see it, is governance staff of the host). A draft is for staff; otherwise the invitees, the
    secretary and staff."""
    staff = GOVERNANCE in effective_permissions(user, meeting.organization)
    invited = meeting.status != Meeting.Status.DRAFT and (
        meeting.secretary_id == user.pk or meeting.invitees.filter(user=user).exists()
    )
    return staff or invited, staff


def reads_document(user, attachment) -> bool:
    """Whether `user` may read the meeting document `attachment`: whoever may see the meeting."""
    document = MeetingDocument.objects.filter(file=attachment).select_related("meeting__organization").first()
    return document is not None and sees_meeting(user, document.meeting)[0]


def reply(request, meeting: Meeting, staff: bool, code=status.HTTP_200_OK) -> Response:
    from .views import is_top, meetings

    found = meetings().get(pk=meeting.pk)
    host = found.organization
    context = {
        "request": request,
        "staff": staff,
        "organization": host,
        "top": is_top(request.user, host),
        "detail": True,
        "tournament_names": tournament_names([found]),
    }
    return Response(MeetingSerializer(found, context=context).data, status=code)


class MeetingAction(APIView):
    """A meeting of the organization in the path, locked. Anyone who can't see it gets not found."""

    permission_classes = [IsAuthenticated]

    def locked(self, request, organization_pk, pk) -> tuple[Meeting, bool]:
        host = get_object_or_404(Organization, pk=organization_pk)
        meeting = get_object_or_404(
            Meeting.objects.select_for_update(of=("self",)).select_related("organization"),
            organization=host,
            pk=pk,
        )
        seen, staff = sees_meeting(request.user, meeting)
        if not seen:
            raise Http404
        return meeting, staff

    def writer(self, request, organization_pk, pk) -> tuple[Meeting, bool]:
        """For whoever writes the minutes: governance staff or the secretary."""
        meeting, staff = self.locked(request, organization_pk, pk)
        if not (staff or meeting.secretary_id == request.user.pk):
            raise ApiException(
                "permission_denied", "Only the secretary or governance staff write the minutes.", 403
            )
        return meeting, staff

    def governor(self, request, organization_pk, pk) -> Meeting:
        meeting, staff = self.locked(request, organization_pk, pk)
        if not staff:
            raise ApiException("permission_denied", "Only governance staff do that.", 403)
        return meeting


def require_held(meeting: Meeting) -> None:
    if meeting.status != Meeting.Status.PUBLISHED or meeting.starts_at > timezone.now():
        raise ApiException("meeting_not_held", "Minutes are recorded once the meeting has started.", 409)


def write_action_items(meeting: Meeting, rows: list[dict], item_ids: set) -> None:
    """Make the meeting's action items match `rows`: change those sent with their id, add the new ones
    and drop the rest."""
    allowed = owner_choices(meeting)
    existing = {action.pk: action for action in meeting.action_items.all()}
    kept = set()
    for row in rows:
        owner = row.get("owner_id")
        if owner is not None and owner not in allowed:
            raise ValidationError({"action_items": "Give an action item to an invitee or a member."})
        fields = {
            "item": row.get("item", "") if row.get("item", "") in item_ids else "",
            "description": row["description"],
            "owner_id": owner,
            "due_on": row.get("due_on"),
        }
        action = existing.get(row.get("id"))
        if row.get("id") and action is None:
            raise ValidationError({"action_items": "One of the action items is no longer there."})
        if action is None:
            kept.add(ActionItem.objects.create(meeting=meeting, **fields).pk)
            continue
        for name, value in fields.items():
            setattr(action, name, value)
        action.save(update_fields=list(fields))
        kept.add(action.pk)
    meeting.action_items.exclude(pk__in=kept).delete()


class MinutesView(MeetingAction):
    """POST .../meetings/{id}/minutes/: save the minutes as a draft once the meeting has started: the
    text, decisions per agenda item, action items and the next meeting's date. Sending the action items
    replaces the list. Approved minutes can't be changed."""

    http_method_names = ["post"]

    @extend_schema(request=MinutesSerializer, responses={200: MeetingSerializer})
    def post(self, request, organization_pk, pk):
        serializer = MinutesSerializer(data=request.data)
        with transaction.atomic():
            meeting, staff = self.writer(request, organization_pk, pk)
            serializer.is_valid(raise_exception=True)
            require_held(meeting)
            if meeting.minutes_status == Meeting.MinutesStatus.APPROVED:
                raise ApiException(
                    "minutes_approved", "Approved minutes can't change. Add an amendment instead.", 409
                )
            data = serializer.validated_data
            item_ids = {row.get("id") for row in meeting.agenda}
            meeting.minutes = data["minutes"]
            if "decisions" in data:
                meeting.decisions = [
                    {"item": row["item"] if row["item"] in item_ids else "", "text": row["text"]}
                    for row in data["decisions"]
                ]
            if "next_meeting_at" in data:
                if data["next_meeting_at"] and data["next_meeting_at"] <= meeting.ends_at:
                    raise ValidationError({"next_meeting_at": "The next meeting comes after this one."})
                meeting.next_meeting_at = data["next_meeting_at"]
            if "action_items" in data:
                write_action_items(meeting, data["action_items"], item_ids)
            meeting.minutes_status = Meeting.MinutesStatus.DRAFT
            meeting.minutes_recorded_at = timezone.now()
            meeting.save(
                update_fields=[
                    "minutes",
                    "decisions",
                    "next_meeting_at",
                    "minutes_status",
                    "minutes_recorded_at",
                ]
            )
        return reply(request, meeting, staff)


def draft_next(meeting: Meeting, actor) -> Meeting | None:
    """The next meeting as a draft on the date the minutes give: same kind, audience, place and length."""
    if meeting.next_meeting_at is None or Meeting.objects.filter(follows=meeting).exists():
        return None
    following = Meeting.objects.create(
        organization=meeting.organization,
        title=meeting.title,
        kind=meeting.kind,
        starts_at=meeting.next_meeting_at,
        ends_at=meeting.next_meeting_at + (meeting.ends_at - meeting.starts_at),
        location=meeting.location,
        online_link=meeting.online_link,
        audience=meeting.audience,
        rules=meeting.rules,
        secretary=meeting.secretary,
        follows=meeting,
        created_by=actor,
    )
    following.named.set(meeting.named.all())
    return following


class ApproveMinutesView(MeetingAction):
    """POST .../meetings/{id}/minutes/approve/: governance staff approve the draft. The invitees can then
    read the minutes, which never change again, and each action item's owner is told."""

    http_method_names = ["post"]

    @extend_schema(request=ApproveMinutesSerializer, responses={200: MeetingSerializer})
    def post(self, request, organization_pk, pk):
        serializer = ApproveMinutesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            meeting = self.governor(request, organization_pk, pk)
            if meeting.minutes_status != Meeting.MinutesStatus.DRAFT:
                raise ApiException("no_draft_minutes", "There are no draft minutes to approve.", 409)
            if meeting.ends_at > timezone.now():
                raise ApiException("meeting_running", "Approve the minutes once the meeting is over.", 409)
            meeting.minutes_status = Meeting.MinutesStatus.APPROVED
            meeting.minutes_approved_by = request.user
            meeting.minutes_approved_at = timezone.now()
            meeting.save(update_fields=["minutes_status", "minutes_approved_by", "minutes_approved_at"])
            if serializer.validated_data["create_next"]:
                draft_next(meeting, request.user)
            tell_invitees(
                meeting,
                f"Minutes of {meeting.title} are ready",
                subject="meeting-minutes",
                version="approved",
                actor=request.user,
            )
            for action in meeting.action_items.exclude(owner=None).exclude(owner=request.user):
                notify(
                    [action.owner_id],
                    Category.MEETING,
                    f"Action for you from {meeting.title}",
                    subject=f"action-item:{action.pk}",
                    body=action.description,
                    link="/action-items",
                    organization=meeting.organization,
                )
        return reply(request, meeting, staff=True)


class AmendMinutesView(MeetingAction):
    """POST .../meetings/{id}/minutes/amendments/: governance staff correct approved minutes. The
    amendment is kept beside the minutes, which stay as approved."""

    http_method_names = ["post"]

    @extend_schema(request=AmendmentInputSerializer, responses={201: MeetingSerializer})
    def post(self, request, organization_pk, pk):
        serializer = AmendmentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            meeting = self.governor(request, organization_pk, pk)
            if meeting.minutes_status != Meeting.MinutesStatus.APPROVED:
                raise ApiException("minutes_not_approved", "Only approved minutes are amended.", 409)
            if meeting.amendments.count() >= 20:
                raise ApiException("too_many_amendments", "These minutes have 20 amendments already.", 409)
            MinutesAmendment.objects.create(
                meeting=meeting, text=serializer.validated_data["text"], created_by=request.user
            )
            tell_invitees(
                meeting,
                f"Minutes of {meeting.title} were amended",
                subject="meeting-minutes",
                version=f"amended{meeting.amendments.count()}",
                actor=request.user,
            )
        return reply(request, meeting, staff=True, code=status.HTTP_201_CREATED)


class ActionItemView(MeetingAction):
    """POST .../meetings/{id}/action-items/{item}/: its owner, governance staff or the secretary mark an
    action item done or open again."""

    http_method_names = ["post"]

    @extend_schema(request=ActionItemStatusSerializer, responses={200: MeetingSerializer})
    def post(self, request, organization_pk, pk, action_pk):
        serializer = ActionItemStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            host = get_object_or_404(Organization, pk=organization_pk)
            action = get_object_or_404(
                ActionItem.objects.select_for_update(of=("self",)).select_related("meeting__organization"),
                pk=action_pk,
                meeting__pk=pk,
                meeting__organization=host,
            )
            meeting = action.meeting
            seen, staff = sees_meeting(request.user, meeting)
            owns = action.owner_id == request.user.pk
            writes = staff or meeting.secretary_id == request.user.pk
            # An owner who wasn't invited still reaches their own item, once the minutes are out.
            approved = meeting.minutes_status == Meeting.MinutesStatus.APPROVED
            if not (writes or (owns and approved)):
                if seen and approved:
                    raise ApiException("permission_denied", "Only its owner or staff change this.", 403)
                raise Http404
            done = serializer.validated_data["status"] == ActionItem.Status.DONE
            action.status = serializer.validated_data["status"]
            action.done_at = timezone.now() if done else None
            action.done_by = request.user if done else None
            action.save(update_fields=["status", "done_at", "done_by"])
        if not seen:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return reply(request, meeting, staff)


class MyActionItemsView(APIView):
    """GET /me/action-items/: the open action items you own from approved minutes, in every organization,
    soonest due first."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MyActionItemSerializer(many=True)})
    def get(self, request):
        mine = (
            ActionItem.objects.filter(
                owner=request.user,
                status=ActionItem.Status.OPEN,
                meeting__minutes_status=Meeting.MinutesStatus.APPROVED,
            )
            .select_related("meeting__organization", "owner")
            .order_by(F("due_on").asc(nulls_last=True), "created_at")
        )
        return Response(
            MyActionItemSerializer(mine[:MAX_MY_ACTION_ITEMS], many=True, context={"request": request}).data
        )


class MeetingDocumentsView(MeetingAction):
    """POST .../meetings/{id}/documents/: governance staff add a PDF, for an agenda item or the meeting."""

    parser_classes = [MultiPartParser]
    throttle_scope = "uploads"
    http_method_names = ["post"]

    @extend_schema(
        request={"multipart/form-data": MeetingDocumentUploadSerializer},
        responses={201: MeetingSerializer},
    )
    def post(self, request, organization_pk, pk):
        if int(request.META.get("CONTENT_LENGTH") or 0) > MAX_DOCUMENT_BYTES + SLACK:
            raise ValidationError({"file": "Choose a PDF under 10 MB."})
        body = MeetingDocumentUploadSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        content = read_pdf(body.validated_data["file"])
        new = None
        try:
            with transaction.atomic():
                meeting = self.governor(request, organization_pk, pk)
                if meeting.status == Meeting.Status.CANCELLED:
                    raise ApiException("meeting_closed", "This meeting was cancelled.", 409)
                if meeting.documents.count() >= MAX_MEETING_DOCUMENTS:
                    raise ApiException(
                        "too_many_documents", f"A meeting can have {MAX_MEETING_DOCUMENTS} documents.", 409
                    )
                item = body.validated_data["item"]
                if item and item not in {row.get("id") for row in meeting.agenda}:
                    raise ValidationError({"item": "That agenda item is no longer there."})
                new = Attachment.store(
                    owner=request.user,
                    purpose=Attachment.Purpose.MEETING_DOCUMENT,
                    content=content,
                    content_type=PDF_CONTENT_TYPE,
                )
                MeetingDocument.objects.create(
                    meeting=meeting, item=item, title=body.validated_data["title"], file=new
                )
                if meeting.status == Meeting.Status.PUBLISHED and meeting.starts_at > timezone.now():
                    revise(meeting, request.user)
        except BaseException:
            if new is not None:
                new.discard_file()
            raise
        return reply(request, meeting, staff=True, code=status.HTTP_201_CREATED)


class MeetingDocumentView(MeetingAction):
    """DELETE .../meetings/{id}/documents/{document}/ removes a document and its file."""

    http_method_names = ["delete"]

    @extend_schema(request=None, responses={200: MeetingSerializer})
    def delete(self, request, organization_pk, pk, document_pk):
        with transaction.atomic():
            meeting = self.governor(request, organization_pk, pk)
            document = get_object_or_404(MeetingDocument, pk=document_pk, meeting=meeting)
            document.file.delete()  # cascades to the document
        return reply(request, meeting, staff=True)


def revise(meeting: Meeting, actor) -> None:
    """A published meeting changed before it started: count it and tell the invitees."""
    meeting.revision += 1
    meeting.save(update_fields=["revision"])
    tell_invitees(
        meeting,
        f"{meeting.title} has changed",
        subject="meeting",
        version=f"rev{meeting.revision}",
        actor=actor,
    )
