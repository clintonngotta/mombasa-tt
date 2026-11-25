"""Regional bodies (REQ-048): set up, their region's clubs, the yearly agenda, articles, meetings and
sponsorships.

Body routes sit under /organizations/{id}/. The region's clubs read the agenda and published articles;
the body's governance staff write the agenda and meetings, announcement staff write articles and competition
staff offer sponsorships. A meeting is shown to its invitees and the host's governance staff only. A
tournament's host club decides the sponsorships offered to it; everyone who sees the tournament sees the
accepted sponsors.
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from competitions.models import Tournament
from core.exceptions import ApiException
from core.models import Country, Region
from core.permissions import PublicReads, is_platform_super_admin
from notifications.models import Category
from notifications.service import notify
from organizations.access import effective_permissions, require_membership, require_permission
from organizations.models import BODY_KINDS, Membership, Organization, Representative, seed_roles
from organizations.permissions import Permission, RoleKey

from . import minutes, service
from .models import AgendaItem, Article, Meeting, MeetingInvitee, MeetingPenalty, Sponsorship
from .serializers import (
    AgendaItemSerializer,
    AnswerSerializer,
    ArticleSerializer,
    AttendanceSerializer,
    CancelSerializer,
    DecisionSerializer,
    MeetingSerializer,
    PenaltySerializer,
    PenaltyUpdateSerializer,
    RegionalBodyInputSerializer,
    RegionalBodySerializer,
    RegionClubSerializer,
    SponsorSerializer,
    SponsorshipSerializer,
)

User = get_user_model()

GOVERNANCE = Permission.GOVERNANCE_MANAGE
ANNOUNCEMENTS = Permission.ANNOUNCEMENTS_MANAGE

COMPETITIONS = Permission.COMPETITIONS_MANAGE


def organization(pk) -> Organization:
    return get_object_or_404(Organization, pk=pk)


def body(pk) -> Organization:
    found = organization(pk)
    service.require_body(found)
    return found


# Bodies -------------------------------------------------------------------------------------------------


class RegionalBodiesView(APIView):
    """GET /regional-bodies/: every regional and national body. POST creates one (TASK-107): only a
    platform super admin, who names its first admin. One body per region and one per country."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: RegionalBodySerializer(many=True)})
    def get(self, request):
        bodies = Organization.objects.filter(kind__in=BODY_KINDS).order_by("kind", "name")
        return Response(RegionalBodySerializer(bodies, many=True).data)

    @extend_schema(request=RegionalBodyInputSerializer, responses={201: RegionalBodySerializer})
    def post(self, request):
        if not is_platform_super_admin(request.user):
            raise ApiException("permission_denied", "Only a platform super admin creates a body.", 403)
        serializer = RegionalBodyInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        found = Country.objects.filter(pk=data["country"]).first()
        if found is None:
            raise ValidationError({"country": "Choose a country from the list."})
        if data["kind"] == service.BODY:
            region = Region.objects.filter(country=found, name__iexact=data["region"]).first()
            if region is None:
                raise ValidationError({"region": "Choose a region of that country from the list."})
            country, region_name, place = found.pk, region.name, region.name
        else:
            country, region_name, place = found.pk, "", found.name
        admin = User.objects.filter(email__iexact=data["admin_email"], is_active=True).first()
        if admin is None:
            raise ValidationError({"admin_email": "No active account uses that email."})
        try:
            with transaction.atomic():
                made = Organization.objects.create(
                    name=data["name"],
                    town=data.get("town") or place,
                    country=country,
                    region=region_name,
                    kind=data["kind"],
                    created_by=request.user,
                )
                roles = seed_roles(made)
                Membership.objects.create(organization=made, user=admin).roles.add(roles[RoleKey.ADMIN])
        except IntegrityError as error:
            raise ApiException("body_exists", f"{place} already has a body of that kind.", 409) from error
        return Response(RegionalBodySerializer(made).data, status=status.HTTP_201_CREATED)


class RegionClubsView(APIView):
    """GET /organizations/{body}/region-clubs/: the region's clubs with member counts and upcoming
    tournaments, for the body's members and the region's officials."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: RegionClubSerializer(many=True)})
    def get(self, request, organization_pk):
        found = body(organization_pk)
        require_membership(request.user, found)
        today = timezone.localdate()
        clubs = service.region_clubs(found).annotate(
            members=Count(
                "memberships", filter=Q(memberships__status=Membership.Status.ACTIVE), distinct=True
            ),
            upcoming_tournaments=Count(
                "tournaments",
                filter=Q(tournaments__ends_on__gte=today)
                & Q(tournaments__status__in=[Tournament.Status.PUBLISHED, Tournament.Status.IN_PROGRESS]),
                distinct=True,
            ),
        )
        return Response(RegionClubSerializer(clubs.order_by("name"), many=True).data)


# Agenda --------------------------------------------------------------------------------------------------


def agenda_year(request, items):
    year = request.query_params.get("year")
    if year:
        if not year.isdigit():
            raise ValidationError({"year": "Use a year such as 2027."})
        items = items.filter(starts_on__year__lte=int(year), ends_on__year__gte=int(year))
    return items


class AgendaView(APIView):
    """GET/POST /organizations/{body}/agenda/: the body's yearly agenda."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("year", int)], responses={200: AgendaItemSerializer(many=True)}
    )
    def get(self, request, organization_pk):
        found = body(organization_pk)
        service.require_reader(request.user, found)
        items = agenda_year(request, found.agenda_items.select_related("organization", "tournament"))
        return Response(AgendaItemSerializer(items, many=True).data)

    @extend_schema(request=AgendaItemSerializer, responses={201: AgendaItemSerializer})
    def post(self, request, organization_pk):
        found = body(organization_pk)
        require_permission(request.user, found, GOVERNANCE)
        serializer = AgendaItemSerializer(data=request.data, context={"organization": found})
        serializer.is_valid(raise_exception=True)
        item = serializer.save(organization=found, created_by=request.user)
        return Response(AgendaItemSerializer(item).data, status=status.HTTP_201_CREATED)


class AgendaItemView(APIView):
    """PATCH/DELETE /organizations/{body}/agenda/{id}/."""

    permission_classes = [IsAuthenticated]

    def item(self, request, organization_pk, pk):
        found = body(organization_pk)
        require_permission(request.user, found, GOVERNANCE)
        return found, get_object_or_404(found.agenda_items, pk=pk)

    @extend_schema(request=AgendaItemSerializer, responses={200: AgendaItemSerializer})
    def patch(self, request, organization_pk, pk):
        found, item = self.item(request, organization_pk, pk)
        serializer = AgendaItemSerializer(
            item, data=request.data, partial=True, context={"organization": found}
        )
        serializer.is_valid(raise_exception=True)
        return Response(AgendaItemSerializer(serializer.save()).data)

    @extend_schema(responses={204: None})
    def delete(self, request, organization_pk, pk):
        self.item(request, organization_pk, pk)[1].delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyAgendaView(APIView):
    """GET /me/agenda/: the agendas of the bodies of your clubs' regions, and of bodies you belong to."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("year", int)], responses={200: AgendaItemSerializer(many=True)}
    )
    def get(self, request):
        items = AgendaItem.objects.filter(organization__in=service.bodies_of(request.user)).select_related(
            "organization", "tournament"
        )
        return Response(AgendaItemSerializer(agenda_year(request, items)[:300], many=True).data)


# Articles ------------------------------------------------------------------------------------------------


def write_clubs(article: Article, found: Organization, data) -> None:
    if "club_ids" not in data:
        return
    wanted = set(data["club_ids"])
    clubs = list(service.region_clubs(found).filter(pk__in=wanted))
    if len(clubs) != len(wanted):
        raise ValidationError({"club_ids": "Choose clubs of the region."})
    article.clubs.set(clubs)


def check_audience(article: Article) -> None:
    if article.audience == Article.Audience.CHOSEN and not article.clubs.exists():
        raise ValidationError({"club_ids": "Choose at least one club, or send it to the whole region."})


def articles():
    return Article.objects.select_related("organization").prefetch_related("clubs")


class ArticlesView(APIView):
    """GET/POST /organizations/{body}/articles/: announcement staff see drafts too; everyone else sees
    the published articles that reach them."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ArticleSerializer(many=True)})
    def get(self, request, organization_pk):
        found = body(organization_pk)
        service.require_reader(request.user, found)
        mine = articles().filter(organization=found)
        if ANNOUNCEMENTS not in effective_permissions(request.user, found):
            mine = service.articles_for(request.user, mine)
        return Response(ArticleSerializer(mine[:100], many=True).data)

    @extend_schema(request=ArticleSerializer, responses={201: ArticleSerializer})
    def post(self, request, organization_pk):
        found = body(organization_pk)
        require_permission(request.user, found, ANNOUNCEMENTS)
        serializer = ArticleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        with transaction.atomic():
            club_ids = data.pop("club_ids", None)
            article = Article.objects.create(organization=found, created_by=request.user, **data)
            if club_ids is not None:
                write_clubs(article, found, {"club_ids": club_ids})
        return Response(ArticleSerializer(articles().get(pk=article.pk)).data, status=status.HTTP_201_CREATED)


class ArticleView(APIView):
    """GET/PATCH/DELETE /organizations/{body}/articles/{id}/."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ArticleSerializer})
    def get(self, request, organization_pk, pk):
        found = body(organization_pk)
        article = get_object_or_404(articles().filter(organization=found), pk=pk)
        staff = ANNOUNCEMENTS in effective_permissions(request.user, found)
        if not staff and not (
            article.status == Article.Status.PUBLISHED and service.article_reaches(request.user, article)
        ):
            raise Http404
        return Response(ArticleSerializer(article).data)

    def staff_article(self, request, organization_pk, pk):
        found = body(organization_pk)
        require_permission(request.user, found, ANNOUNCEMENTS)
        return found, get_object_or_404(Article.objects.select_for_update(), organization=found, pk=pk)

    @extend_schema(request=ArticleSerializer, responses={200: ArticleSerializer})
    def patch(self, request, organization_pk, pk):
        with transaction.atomic():
            found, article = self.staff_article(request, organization_pk, pk)
            serializer = ArticleSerializer(article, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            data = dict(serializer.validated_data)
            club_ids = data.pop("club_ids", None)
            for name, value in data.items():
                setattr(article, name, value)
            article.save()
            if club_ids is not None:
                write_clubs(article, found, {"club_ids": club_ids})
            if article.status == Article.Status.PUBLISHED:
                check_audience(article)
        return Response(ArticleSerializer(articles().get(pk=article.pk)).data)

    @extend_schema(responses={204: None})
    def delete(self, request, organization_pk, pk):
        with transaction.atomic():
            self.staff_article(request, organization_pk, pk)[1].delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PublishArticleView(ArticleView):
    """POST /organizations/{body}/articles/{id}/publish/: send it to its clubs."""

    http_method_names = ["post"]

    @extend_schema(request=None, responses={200: ArticleSerializer})
    def post(self, request, organization_pk, pk):
        with transaction.atomic():
            _, article = self.staff_article(request, organization_pk, pk)
            check_audience(article)
            if article.status != Article.Status.PUBLISHED:
                article.status = Article.Status.PUBLISHED
                article.published_at = timezone.now()
                article.save(update_fields=["status", "published_at", "updated_at"])
        return Response(ArticleSerializer(articles().get(pk=article.pk)).data)


class MyArticlesView(APIView):
    """GET /me/articles/: published articles from regional bodies to your clubs, newest first."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ArticleSerializer(many=True)})
    def get(self, request):
        return Response(
            ArticleSerializer(service.articles_for(request.user, articles())[:50], many=True).data
        )


# Meetings ------------------------------------------------------------------------------------------------


def meetings():
    return Meeting.objects.select_related("organization", "secretary", "next_meeting").prefetch_related(
        "invitees", "documents", "action_items__owner", "amendments__created_by"
    )


def is_top(user, organization: Organization) -> bool:
    """The organization's admin (the club, facility or body admin) or a platform super admin: the only
    people who change a penalty once it is issued."""
    return is_platform_super_admin(user) or Membership.objects.admins(organization).filter(user=user).exists()


def meeting_reply(request, meeting: Meeting, staff: bool, code=status.HTTP_200_OK) -> Response:
    return minutes.reply(request, meeting, staff, code)


def list_context(request, found_meetings, **extra) -> dict:
    return {"request": request, "tournament_names": minutes.tournament_names(found_meetings), **extra}


def secretary_of(organization: Organization, user_id):
    """The secretary asked for: an active member of the host."""
    if user_id is None:
        return None
    member = (
        Membership.objects.active().filter(organization=organization, user_id=user_id).select_related("user")
    )
    found = member.first()
    if found is None:
        raise ValidationError({"secretary_id": "Choose an active member as secretary."})
    return found.user


MAX_INVITEES = 2000


def invite(meeting: Meeting) -> None:
    """Fix the invitees from the audience when the meeting is published."""
    host = meeting.organization
    people: dict = {}
    if meeting.audience == Meeting.Audience.COMMITTEE:
        people = {user.pk: (user, None) for user in service.committee_users(host)}
    elif meeting.audience == Meeting.Audience.MEMBERS:
        people = {
            m.user_id: (m.user, None)
            for m in Membership.objects.active().filter(organization=host).select_related("user")
        }
    elif meeting.audience == Meeting.Audience.CLUB_ADMINS:
        for club in service.region_clubs(host):
            for admin in Membership.objects.admins(club).select_related("user"):
                people.setdefault(admin.user_id, (admin.user, club))
    elif meeting.audience == Meeting.Audience.REPRESENTATIVES:
        today = timezone.localdate()
        seated = (
            Representative.objects.filter(body=host, status=Representative.Status.ACCEPTED)
            .filter(Q(term_end__isnull=True) | Q(term_end__gte=today))
            .select_related("user", "sender")[:MAX_INVITEES]
        )
        people = {seat.user_id: (seat.user, seat.sender) for seat in seated}
    else:
        people = {user.pk: (user, None) for user in meeting.named.all()}
    if not people:
        raise ApiException(
            "no_invitees", "Nobody would be invited. Choose another audience or name people.", 409
        )
    MeetingInvitee.objects.bulk_create(
        [MeetingInvitee(meeting=meeting, user=user, club=club) for user, club in people.values()],
        ignore_conflicts=True,
    )


class MeetingsView(APIView):
    """GET/POST /organizations/{org}/meetings/: governance staff see every meeting; others see the
    published meetings they are invited to."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MeetingSerializer(many=True)})
    def get(self, request, organization_pk):
        found = organization(organization_pk)
        staff = GOVERNANCE in effective_permissions(request.user, found)
        found_meetings = meetings().filter(organization=found)
        if not staff:
            found_meetings = found_meetings.filter(invitees__user=request.user).exclude(
                status=Meeting.Status.DRAFT
            )
        shown = list(found_meetings.distinct()[:100])
        context = list_context(
            request, shown, staff=staff, organization=found, top=is_top(request.user, found)
        )
        return Response(MeetingSerializer(shown, many=True, context=context).data)

    @extend_schema(request=MeetingSerializer, responses={201: MeetingSerializer})
    def post(self, request, organization_pk):
        found = organization(organization_pk)
        require_permission(request.user, found, GOVERNANCE)
        serializer = MeetingSerializer(data=request.data, context={"request": request, "organization": found})
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        named = data.pop("named_ids", [])
        data["secretary"] = (
            secretary_of(found, data.pop("secretary_id")) if "secretary_id" in data else request.user
        )
        with transaction.atomic():
            meeting = Meeting.objects.create(organization=found, created_by=request.user, **data)
            meeting.named.set(
                Membership.objects.active()
                .filter(organization=found, user__in=named)
                .values_list("user", flat=True)
            )
        return meeting_reply(request, meeting, staff=True, code=status.HTTP_201_CREATED)


class MeetingView(APIView):
    """GET/PATCH/DELETE /organizations/{org}/meetings/{id}/. Staff change a meeting until it starts and
    delete a draft; invitees read it."""

    permission_classes = [IsAuthenticated]

    def find(self, request, organization_pk, pk, *, lock=False):
        found = organization(organization_pk)
        staff = GOVERNANCE in effective_permissions(request.user, found)
        query = Meeting.objects.select_for_update() if lock else meetings()
        meeting = get_object_or_404(query, organization=found, pk=pk)
        invited = meeting.status != Meeting.Status.DRAFT and (
            meeting.secretary_id == request.user.pk or meeting.invitees.filter(user=request.user).exists()
        )
        if not (staff or invited):
            raise Http404
        return found, meeting, staff

    @extend_schema(responses={200: MeetingSerializer})
    def get(self, request, organization_pk, pk):
        _, meeting, staff = self.find(request, organization_pk, pk)
        return meeting_reply(request, meeting, staff)

    @extend_schema(request=MeetingSerializer, responses={200: MeetingSerializer})
    def patch(self, request, organization_pk, pk):
        with transaction.atomic():
            found, meeting, staff = self.find(request, organization_pk, pk, lock=True)
            if not staff:
                raise ApiException("permission_denied", "Only governance staff change a meeting.", 403)
            if meeting.status == Meeting.Status.CANCELLED or meeting.starts_at <= timezone.now():
                raise ApiException(
                    "meeting_closed", "A meeting can't change once it has started or been cancelled.", 409
                )
            serializer = MeetingSerializer(
                meeting, data=request.data, partial=True, context={"request": request, "organization": found}
            )
            serializer.is_valid(raise_exception=True)
            data = dict(serializer.validated_data)
            if meeting.status == Meeting.Status.PUBLISHED and ("audience" in data or "named_ids" in data):
                raise ApiException("invitees_fixed", "Invitees are fixed once the meeting is published.", 409)
            named = data.pop("named_ids", None)
            if "secretary_id" in data:
                data["secretary"] = secretary_of(found, data.pop("secretary_id"))
            changed = any(getattr(meeting, name) != value for name, value in data.items())
            if "agenda" in data:
                # Documents of an item that was removed stay with the meeting.
                kept = {row["id"] for row in data["agenda"]}
                meeting.documents.exclude(item="").exclude(item__in=kept).update(item="")
            for name, value in data.items():
                setattr(meeting, name, value)
            meeting.save()
            if changed and meeting.status == Meeting.Status.PUBLISHED:
                minutes.revise(meeting, request.user)
            if named is not None:
                meeting.named.set(
                    Membership.objects.active()
                    .filter(organization=found, user__in=named)
                    .values_list("user", flat=True)
                )
        return meeting_reply(request, meeting, staff=True)

    @extend_schema(responses={204: None})
    def delete(self, request, organization_pk, pk):
        with transaction.atomic():
            _, meeting, staff = self.find(request, organization_pk, pk, lock=True)
            if not staff:
                raise ApiException("permission_denied", "Only governance staff remove a meeting.", 403)
            if meeting.status != Meeting.Status.DRAFT:
                raise ApiException("already_published", "Cancel a published meeting instead.", 409)
            meeting.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeetingStaffAction(MeetingView):
    http_method_names = ["post"]

    def staff_meeting(self, request, organization_pk, pk):
        found = organization(organization_pk)
        require_permission(request.user, found, GOVERNANCE)
        return get_object_or_404(Meeting.objects.select_for_update(), organization=found, pk=pk)


class PublishMeetingView(MeetingStaffAction):
    """POST .../meetings/{id}/publish/: invite the audience."""

    @extend_schema(request=None, responses={200: MeetingSerializer})
    def post(self, request, organization_pk, pk):
        with transaction.atomic():
            meeting = self.staff_meeting(request, organization_pk, pk)
            if meeting.status != Meeting.Status.DRAFT:
                raise ApiException("already_published", "This meeting is already out.", 409)
            if meeting.starts_at <= timezone.now():
                raise ApiException("meeting_past", "Move the meeting to a time that hasn't passed.", 409)
            invite(meeting)
            meeting.status = Meeting.Status.PUBLISHED
            meeting.published_at = timezone.now()
            meeting.save(update_fields=["status", "published_at"])
            minutes.tell_invitees(
                meeting,
                f"You're invited: {meeting.title}",
                subject="meeting",
                version="published",
                actor=request.user,
            )
        return meeting_reply(request, meeting, staff=True)


class CancelMeetingView(MeetingStaffAction):
    """POST .../meetings/{id}/cancel/ with a reason."""

    @extend_schema(request=CancelSerializer, responses={200: MeetingSerializer})
    def post(self, request, organization_pk, pk):
        serializer = CancelSerializer(data=request.data)
        with transaction.atomic():
            meeting = self.staff_meeting(request, organization_pk, pk)
            serializer.is_valid(raise_exception=True)
            if meeting.status != Meeting.Status.PUBLISHED or meeting.starts_at <= timezone.now():
                raise ApiException(
                    "meeting_closed", "Only a published meeting that hasn't started can be cancelled.", 409
                )
            meeting.status = Meeting.Status.CANCELLED
            meeting.cancel_reason = serializer.validated_data["reason"]
            meeting.save(update_fields=["status", "cancel_reason"])
            minutes.tell_invitees(
                meeting,
                f"Cancelled: {meeting.title}",
                subject="meeting",
                version="cancelled",
                actor=request.user,
            )
        return meeting_reply(request, meeting, staff=True)


class InviteeAction(MeetingView):
    http_method_names = ["post"]

    def invitation(self, request, organization_pk, pk) -> MeetingInvitee:
        found = organization(organization_pk)
        return get_object_or_404(
            MeetingInvitee.objects.select_for_update().select_related("meeting__organization"),
            meeting__organization=found,
            meeting__pk=pk,
            meeting__status=Meeting.Status.PUBLISHED,
            user=request.user,
        )


class AnswerMeetingView(InviteeAction):
    """POST .../meetings/{id}/answer/: attending or apologies, until it ends."""

    @extend_schema(request=AnswerSerializer, responses={200: MeetingSerializer})
    def post(self, request, organization_pk, pk):
        with transaction.atomic():
            invitation = self.invitation(request, organization_pk, pk)
            serializer = AnswerSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            if invitation.meeting.ends_at <= timezone.now():
                raise ApiException("meeting_over", "This meeting is over.", 409)
            invitation.answer = serializer.validated_data["answer"]
            invitation.save(update_fields=["answer"])
        return meeting_reply(request, invitation.meeting, staff=False)


class CheckInMeetingView(InviteeAction):
    """POST .../meetings/{id}/check-in/: an invitee marks themselves present while it runs."""

    @extend_schema(request=None, responses={200: MeetingSerializer})
    def post(self, request, organization_pk, pk):
        with transaction.atomic():
            invitation = self.invitation(request, organization_pk, pk)
            now = timezone.now()
            if not (invitation.meeting.starts_at <= now < invitation.meeting.ends_at):
                raise ApiException(
                    "not_in_progress", "You can check in only while the meeting is running.", 409
                )
            if invitation.checked_in_at is None:
                invitation.checked_in_at = now
                invitation.answer = MeetingInvitee.Answer.ATTENDING
                fields = ["checked_in_at", "answer"]
                if not invitation.attendance:  # the secretary's mark, if any, stands
                    invitation.attendance = MeetingInvitee.Attendance.PRESENT
                    invitation.marked_at = now
                    fields += ["attendance", "marked_at"]
                invitation.save(update_fields=fields)
        return meeting_reply(request, invitation.meeting, staff=False)


class SecretaryAction(MeetingView):
    """Attendance and penalties: the host's governance staff or the meeting's secretary."""

    http_method_names = ["post"]

    def held_meeting(self, request, organization_pk, pk) -> tuple[Meeting, bool]:
        found = organization(organization_pk)
        meeting = get_object_or_404(Meeting.objects.select_for_update(), organization=found, pk=pk)
        staff = GOVERNANCE in effective_permissions(request.user, found)
        if not (staff or meeting.secretary_id == request.user.pk):
            if staff or meeting.invitees.filter(user=request.user).exists():
                raise ApiException(
                    "permission_denied", "Only the secretary or governance staff take attendance.", 403
                )
            raise Http404
        if meeting.status != Meeting.Status.PUBLISHED or meeting.starts_at > timezone.now():
            raise ApiException("meeting_not_held", "Attendance is taken once the meeting has started.", 409)
        return meeting, staff


class AttendanceView(SecretaryAction):
    """POST .../meetings/{id}/attendance/: mark one invitee present, late, apologies or absent, during the
    meeting or after it. A mark can't change once a penalty has been issued for it."""

    @extend_schema(request=AttendanceSerializer, responses={200: MeetingSerializer})
    def post(self, request, organization_pk, pk):
        serializer = AttendanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            meeting, staff = self.held_meeting(request, organization_pk, pk)
            invitee = get_object_or_404(
                MeetingInvitee.objects.select_for_update(),
                meeting=meeting,
                pk=serializer.validated_data["invitee"],
            )
            if MeetingPenalty.objects.filter(invitee=invitee).exists():
                raise ApiException(
                    "penalty_issued", "A penalty has been issued for this; the admin can change it.", 409
                )
            invitee.attendance = serializer.validated_data["attendance"]
            invitee.marked_by = request.user
            invitee.marked_at = timezone.now()
            invitee.save(update_fields=["attendance", "marked_by", "marked_at"])
        return meeting_reply(request, meeting, staff)


def final_attendance(invitee: MeetingInvitee) -> str:
    """What the record says once the meeting is over: the mark, else apologies if sent, else absent."""
    if invitee.attendance:
        return invitee.attendance
    if invitee.answer == MeetingInvitee.Answer.APOLOGIES:
        return MeetingInvitee.Attendance.APOLOGIES
    return MeetingInvitee.Attendance.ABSENT


class IssuePenaltiesView(SecretaryAction):
    """POST .../meetings/{id}/penalties/: once the meeting is over, close the attendance record (anyone
    unmarked is absent, or apologies if they sent them) and issue the penalties its rules set. Run again,
    it issues only for invitees who have none yet."""

    @extend_schema(request=None, responses={200: MeetingSerializer})
    def post(self, request, organization_pk, pk):
        with transaction.atomic():
            meeting, staff = self.held_meeting(request, organization_pk, pk)
            if meeting.ends_at > timezone.now():
                raise ApiException("meeting_running", "Issue penalties once the meeting is over.", 409)
            rules = {rule["applies_to"]: rule for rule in meeting.rules}
            if not rules:
                raise ApiException("no_rules", "This meeting has no penalty rules.", 409)
            now = timezone.now()
            for invitee in meeting.invitees.filter(penalty__isnull=True):  # the meeting row is locked
                if not invitee.attendance:
                    invitee.attendance = final_attendance(invitee)
                    invitee.marked_by, invitee.marked_at = request.user, now
                    invitee.save(update_fields=["attendance", "marked_by", "marked_at"])
                rule = rules.get(invitee.attendance)
                if rule:
                    penalty = MeetingPenalty.objects.create(
                        invitee=invitee,
                        applies_to=invitee.attendance,
                        penalty=rule["penalty"],
                        amount_minor=rule.get("amount_minor"),
                        issued_by=request.user,
                    )
                    notify(
                        [invitee.user_id],
                        Category.MEETING,
                        f"Penalty from {meeting.title}",
                        subject=f"meeting-penalty:{penalty.pk}",
                        body=rule["penalty"],
                        link=minutes.link(meeting),
                        organization=meeting.organization,
                    )
        return meeting_reply(request, meeting, staff)


class PenaltyView(APIView):
    """PATCH .../meetings/{id}/penalties/{penalty}/: change, waive or mark paid an issued penalty. Only
    the host's admin or a platform super admin; each change is kept in the penalty's history."""

    permission_classes = [IsAuthenticated]
    http_method_names = ["patch"]

    @extend_schema(request=PenaltyUpdateSerializer, responses={200: PenaltySerializer})
    def patch(self, request, organization_pk, pk, penalty_pk):
        found = organization(organization_pk)
        if not is_top(request.user, found):
            raise ApiException(
                "permission_denied", "Only the admin can change a penalty once it is issued.", 403
            )
        serializer = PenaltyUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            penalty = get_object_or_404(
                MeetingPenalty.objects.select_for_update(),
                pk=penalty_pk,
                invitee__meeting__pk=pk,
                invitee__meeting__organization=found,
            )
            changes = {}
            for name, value in serializer.validated_data.items():
                if getattr(penalty, name) != value:
                    changes[name] = [getattr(penalty, name), value]
                    setattr(penalty, name, value)
            if changes:
                penalty.history = [
                    *penalty.history,
                    {
                        "at": timezone.now().isoformat(),
                        "by": str(request.user.pk),
                        "by_name": request.user.display_name,
                        "changes": changes,
                    },
                ]
                penalty.save()
        return Response(PenaltySerializer(penalty).data)


class MyMeetingsView(APIView):
    """GET /me/meetings/: meetings you are invited to, upcoming first, with your answer."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MeetingSerializer(many=True)})
    def get(self, request):
        found = (
            meetings()
            .filter(invitees__user=request.user)
            .exclude(status=Meeting.Status.DRAFT)
            .filter(ends_at__gte=timezone.now() - timezone.timedelta(days=90))
            .order_by("starts_at")
            .distinct()
        )
        shown = list(found[:100])
        return Response(
            MeetingSerializer(shown, many=True, context=list_context(request, shown, staff=False)).data
        )


# Sponsorships --------------------------------------------------------------------------------------------


def sponsorships():
    return Sponsorship.objects.select_related("sponsor", "tournament")


class SponsorshipsView(APIView):
    """GET/POST /organizations/{org}/sponsorships/: what the organization offers tournaments, for its
    competition staff."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: SponsorshipSerializer(many=True)})
    def get(self, request, organization_pk):
        found = organization(organization_pk)
        require_permission(request.user, found, COMPETITIONS)
        return Response(SponsorshipSerializer(sponsorships().filter(sponsor=found)[:200], many=True).data)

    @extend_schema(request=SponsorshipSerializer, responses={201: SponsorshipSerializer})
    def post(self, request, organization_pk):
        found = organization(organization_pk)
        require_permission(request.user, found, COMPETITIONS)
        serializer = SponsorshipSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        tournament = (
            Tournament.objects.filter(pk=data.pop("tournament_id"))
            .exclude(status=Tournament.Status.DRAFT)
            .first()
        )
        if tournament is None or tournament.status in (
            Tournament.Status.COMPLETED,
            Tournament.Status.CANCELLED,
        ):
            raise ValidationError({"tournament_id": "Choose a published tournament that hasn't finished."})
        if tournament.organization_id == found.pk:
            raise ValidationError({"tournament_id": "An organization doesn't sponsor its own tournament."})
        try:
            with transaction.atomic():
                offer = Sponsorship.objects.create(
                    sponsor=found, tournament=tournament, offered_by=request.user, **data
                )
        except IntegrityError as error:
            raise ApiException(
                "already_offered", "You already have an offer for this tournament.", 409
            ) from error
        return Response(
            SponsorshipSerializer(sponsorships().get(pk=offer.pk)).data, status=status.HTTP_201_CREATED
        )


class WithdrawSponsorshipView(APIView):
    """POST /organizations/{org}/sponsorships/{id}/withdraw/: before the host has decided, or after it
    accepted (the sponsor pulls out)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=DecisionSerializer, responses={200: SponsorshipSerializer})
    def post(self, request, organization_pk, pk):
        found = organization(organization_pk)
        require_permission(request.user, found, COMPETITIONS)
        serializer = DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            offer = get_object_or_404(Sponsorship.objects.select_for_update(), sponsor=found, pk=pk)
            if offer.status not in (Sponsorship.Status.OFFERED, Sponsorship.Status.ACCEPTED):
                raise ApiException("not_open", "This offer is no longer open.", 409)
            offer.status = Sponsorship.Status.WITHDRAWN
            offer.reason = serializer.validated_data["reason"]
            offer.decided_by, offer.decided_at = request.user, timezone.now()
            offer.save()
        return Response(SponsorshipSerializer(sponsorships().get(pk=offer.pk)).data)


class TournamentSponsorshipsView(APIView):
    """GET /tournaments/{id}/sponsorships/: every offer, for the host's competition staff."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: SponsorshipSerializer(many=True)})
    def get(self, request, tournament_pk):
        tournament = get_object_or_404(Tournament.objects.select_related("organization"), pk=tournament_pk)
        require_permission(request.user, tournament.organization, COMPETITIONS)
        return Response(SponsorshipSerializer(sponsorships().filter(tournament=tournament), many=True).data)


class TournamentSponsorsView(APIView):
    """GET /tournaments/{id}/sponsors/: the accepted sponsors, for everyone who can see the tournament."""

    permission_classes = [PublicReads]
    public_actions = ("get",)  # TASK-035

    @extend_schema(responses={200: SponsorSerializer(many=True)})
    def get(self, request, tournament_pk):
        tournament = get_object_or_404(Tournament.objects.select_related("organization"), pk=tournament_pk)
        if tournament.status == Tournament.Status.DRAFT and COMPETITIONS not in effective_permissions(
            request.user, tournament.organization
        ):
            raise Http404
        accepted = sponsorships().filter(tournament=tournament, status=Sponsorship.Status.ACCEPTED)
        return Response(SponsorSerializer(accepted, many=True).data)


class DecideSponsorshipView(APIView):
    """POST /tournaments/{id}/sponsorships/{offer}/{accept|decline}/: the host club decides."""

    permission_classes = [IsAuthenticated]
    action = ""

    @extend_schema(request=DecisionSerializer, responses={200: SponsorshipSerializer})
    def post(self, request, tournament_pk, pk):
        tournament = get_object_or_404(Tournament.objects.select_related("organization"), pk=tournament_pk)
        require_permission(request.user, tournament.organization, COMPETITIONS)
        serializer = DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            offer = get_object_or_404(Sponsorship.objects.select_for_update(), tournament=tournament, pk=pk)
            if offer.status != Sponsorship.Status.OFFERED:
                raise ApiException("not_offered", "This offer has already been decided.", 409)
            offer.status = (
                Sponsorship.Status.ACCEPTED if self.action == "accept" else Sponsorship.Status.DECLINED
            )
            offer.reason = serializer.validated_data["reason"]
            offer.decided_by, offer.decided_at = request.user, timezone.now()
            offer.save()
        return Response(SponsorshipSerializer(sponsorships().get(pk=offer.pk)).data)
