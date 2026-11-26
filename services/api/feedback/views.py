"""Feedback forms (REQ-055).

The host's competition staff build forms and templates under /organizations/{id}/feedback-forms/, send a
form to a tournament's attendees, and read totals and a CSV export. Whoever was asked answers at
/feedback-forms/{id}/; anybody else gets not found. An anonymous form never tells staff who answered what.
"""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from competitions.models import Tournament
from core.exceptions import ApiException
from notifications.models import Category
from notifications.service import notify
from organizations.access import require_permission
from organizations.models import Membership, Organization
from organizations.permissions import Permission
from profiles.models import listed_profiles

from . import service
from .models import FeedbackForm, FeedbackRecipient, FeedbackResponse
from .serializers import (
    FeedbackAnswersSerializer,
    FeedbackClosingSerializer,
    FeedbackFormSerializer,
    FeedbackTotalsSerializer,
    MyFeedbackFormSerializer,
    SendFeedbackFormSerializer,
)

MANAGE = Permission.COMPETITIONS_MANAGE
MAX_FORMS = 100
MAX_OPEN_DAYS = 180
User = get_user_model()


def forms():
    return (
        FeedbackForm.objects.select_related("organization", "tournament")
        .prefetch_related("guests")
        .annotate(
            recipient_count=Count("recipients", distinct=True),
            response_count=Count("responses", distinct=True),
        )
    )


def reply(form: FeedbackForm, code=status.HTTP_200_OK) -> Response:
    return Response(FeedbackFormSerializer(forms().get(pk=form.pk)).data, status=code)


def staff_organization(request, organization_pk) -> Organization:
    organization = get_object_or_404(Organization, pk=organization_pk)
    require_permission(request.user, organization, MANAGE)
    return organization


def guests_for(organization: Organization, ids) -> list:
    """Named guests: active members of the host or players listed in the directory."""
    wanted = set(ids)
    allowed = set(
        Membership.objects.active()
        .filter(organization=organization, user__in=wanted)
        .values_list("user_id", flat=True)
    ) | set(listed_profiles().filter(user__in=wanted).values_list("user_id", flat=True))
    if wanted - allowed:
        raise ValidationError({"guest_ids": "Name members or players listed in the directory."})
    return list(allowed)


def tournament_for(organization: Organization, pk):
    tournament = Tournament.objects.filter(pk=pk, organization=organization).first()
    if tournament is None:
        raise ValidationError({"tournament_id": "Choose one of this organization's tournaments."})
    return tournament


class FeedbackFormsView(APIView):
    """GET/POST /organizations/{org}/feedback-forms/: the organization's forms, newest first, for its
    competition staff. `?tournament=` lists one tournament's; `?templates=1` the templates. POST makes a
    draft, or a template with `is_template`; `copy_from` starts from another form's sections."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("tournament", OpenApiTypes.UUID), OpenApiParameter("templates", bool)],
        responses={200: FeedbackFormSerializer(many=True)},
    )
    def get(self, request, organization_pk):
        organization = staff_organization(request, organization_pk)
        found = forms().filter(organization=organization)
        if request.query_params.get("templates") in ("1", "true"):
            found = found.filter(is_template=True)
        elif request.query_params.get("tournament"):
            try:
                found = found.filter(tournament=request.query_params["tournament"], is_template=False)
            except (ValueError, ValidationError):
                found = found.none()
        return Response(FeedbackFormSerializer(found[:MAX_FORMS], many=True).data)

    @extend_schema(request=FeedbackFormSerializer, responses={201: FeedbackFormSerializer})
    def post(self, request, organization_pk):
        organization = staff_organization(request, organization_pk)
        body = FeedbackFormSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        guest_ids = data.pop("guest_ids", [])
        copy_from = data.pop("copy_from", None)
        tournament_id = data.pop("tournament_id", None)
        template = data.get("is_template", False)
        if template == bool(tournament_id):
            raise ValidationError({"tournament_id": "A form is for one tournament; a template is for none."})
        with transaction.atomic():
            if copy_from is not None:
                source = FeedbackForm.objects.filter(organization=organization, pk=copy_from).first()
                if source is None:
                    raise ValidationError({"copy_from": "That form isn't one of this organization's."})
                data.setdefault("sections", service.copied_sections(source.sections))
                data.setdefault("intro", source.intro)
            if FeedbackForm.objects.filter(organization=organization).count() >= 500:
                raise ApiException("too_many_forms", "Remove old drafts or templates first.", 409)
            form = FeedbackForm.objects.create(
                organization=organization,
                tournament=None if template else tournament_for(organization, tournament_id),
                created_by=request.user,
                **data,
            )
            if not template:
                form.guests.set(guests_for(organization, guest_ids))
        return reply(form, status.HTTP_201_CREATED)


class FormAction(APIView):
    permission_classes = [IsAuthenticated]

    def locked(self, request, organization_pk, pk) -> FeedbackForm:
        organization = staff_organization(request, organization_pk)
        return get_object_or_404(
            FeedbackForm.objects.select_for_update(of=("self",)).select_related("organization", "tournament"),
            organization=organization,
            pk=pk,
        )


class FeedbackFormView(FormAction):
    """GET/PATCH/DELETE /organizations/{org}/feedback-forms/{id}/. A draft or a template can be changed
    and removed; once a form is sent its questions and recipients are fixed."""

    @extend_schema(responses={200: FeedbackFormSerializer})
    def get(self, request, organization_pk, pk):
        organization = staff_organization(request, organization_pk)
        return Response(
            FeedbackFormSerializer(get_object_or_404(forms(), organization=organization, pk=pk)).data
        )

    @extend_schema(request=FeedbackFormSerializer, responses={200: FeedbackFormSerializer})
    def patch(self, request, organization_pk, pk):
        with transaction.atomic():
            form = self.locked(request, organization_pk, pk)
            if form.status != FeedbackForm.Status.DRAFT:
                raise ApiException("form_sent", "A sent form can't change. Copy it to ask again.", 409)
            body = FeedbackFormSerializer(form, data=request.data, partial=True)
            body.is_valid(raise_exception=True)
            data = dict(body.validated_data)
            for fixed in ("is_template", "tournament_id", "copy_from"):
                if fixed in data:
                    raise ValidationError({fixed: "That is set when the form is made."})
            guest_ids = data.pop("guest_ids", None)
            for name, value in data.items():
                setattr(form, name, value)
            form.save()
            if guest_ids is not None and not form.is_template:
                form.guests.set(guests_for(form.organization, guest_ids))
        return reply(form)

    @extend_schema(responses={204: None})
    def delete(self, request, organization_pk, pk):
        with transaction.atomic():
            form = self.locked(request, organization_pk, pk)
            if form.status != FeedbackForm.Status.DRAFT:
                raise ApiException("form_sent", "A sent form keeps its answers and can't be removed.", 409)
            form.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SendFormView(FormAction):
    """POST .../feedback-forms/{id}/send/: fix who is asked (the tournament's accepted players, umpires,
    the host's competition staff and named guests, as the form says) and open it until `closes_at`."""

    @extend_schema(request=SendFeedbackFormSerializer, responses={200: FeedbackFormSerializer})
    def post(self, request, organization_pk, pk):
        body = SendFeedbackFormSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        now = timezone.now()
        opens = body.validated_data.get("opens_at") or now
        closes = body.validated_data["closes_at"]
        if closes <= max(opens, now):
            raise ValidationError({"closes_at": "It closes after it opens, at a time still to come."})
        if (closes - opens).days > MAX_OPEN_DAYS:
            raise ValidationError({"closes_at": f"Keep a form open for at most {MAX_OPEN_DAYS} days."})
        with transaction.atomic():
            form = self.locked(request, organization_pk, pk)
            if form.is_template:
                raise ApiException("is_template", "A template isn't sent. Make a form from it.", 409)
            if form.status != FeedbackForm.Status.DRAFT:
                raise ApiException("form_sent", "This form was already sent.", 409)
            if not service.questions(form):
                raise ApiException("no_questions", "Add a question before sending.", 409)
            people = service.recipient_ids(form)
            if not people:
                raise ApiException("no_recipients", "Nobody would be asked. Choose who it is for.", 409)
            FeedbackRecipient.objects.bulk_create(
                [FeedbackRecipient(form=form, user_id=pk) for pk in people], ignore_conflicts=True
            )
            form.status, form.opens_at, form.closes_at, form.sent_at = "sent", opens, closes, now
            form.save(update_fields=["status", "opens_at", "closes_at", "sent_at"])
            notify(
                people - {request.user.pk},
                Category.FEEDBACK,
                f"Tell us how it went: {form.title}",
                subject=f"feedback:{form.pk}",
                body=form.tournament.name,
                link=f"/feedback/{form.pk}",
                organization=form.organization,
            )
        return reply(form)


class ClosingView(FormAction):
    """POST .../feedback-forms/{id}/closing/: move a sent form's closing time: later to keep it open, or
    to now to close it."""

    @extend_schema(request=FeedbackClosingSerializer, responses={200: FeedbackFormSerializer})
    def post(self, request, organization_pk, pk):
        body = FeedbackClosingSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        closes = body.validated_data["closes_at"]
        with transaction.atomic():
            form = self.locked(request, organization_pk, pk)
            if form.status != FeedbackForm.Status.SENT:
                raise ApiException("not_sent", "Only a sent form has a closing time.", 409)
            closes = max(closes, timezone.now())
            if closes <= form.opens_at or (closes - form.opens_at).days > MAX_OPEN_DAYS:
                raise ValidationError({"closes_at": f"Within {MAX_OPEN_DAYS} days of when it opened."})
            form.closes_at = closes
            form.save(update_fields=["closes_at"])
        return reply(form)


class TotalsView(APIView):
    """GET .../feedback-forms/{id}/totals/: how many answered, and per question the average, the count
    per choice or the text answers. No names, whether the form is anonymous or not."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: FeedbackTotalsSerializer})
    def get(self, request, organization_pk, pk):
        organization = staff_organization(request, organization_pk)
        form = get_object_or_404(FeedbackForm, organization=organization, pk=pk)
        return Response(FeedbackTotalsSerializer(service.totals(form)).data)


class ExportView(APIView):
    """GET .../feedback-forms/{id}/export.csv: one row per response. A named form includes who answered
    and when; an anonymous one never does."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={(200, "text/csv"): OpenApiTypes.STR})
    def get(self, request, organization_pk, pk):
        organization = staff_organization(request, organization_pk)
        form = get_object_or_404(FeedbackForm, organization=organization, pk=pk)
        response = HttpResponse(service.export_csv(form), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="feedback.csv"'
        return response


# Whoever was asked ------------------------------------------------------------------------------------


def my_context(user, found: list) -> dict:
    """Whether the user answered each form, and their answers, in two queries for the whole list."""
    answered = set(
        FeedbackRecipient.objects.filter(user=user, form__in=found, answered=True).values_list(
            "form_id", flat=True
        )
    )
    keys = {service.owner_key(form, user): form.pk for form in found if form.pk in answered}
    answers = {
        keys[key]: given
        for key, given in FeedbackResponse.objects.filter(owner_key__in=keys).values_list(
            "owner_key", "answers"
        )
    }
    return {"answered": answered, "answers": answers}


def asked(user):
    return (
        FeedbackForm.objects.filter(status=FeedbackForm.Status.SENT, recipients__user=user)
        .select_related("organization", "tournament")
        .distinct()
    )


class MyFeedbackFormsView(APIView):
    """GET /me/feedback-forms/: forms you were asked to answer that are open now, closing soonest first,
    each with whether you answered."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MyFeedbackFormSerializer(many=True)})
    def get(self, request):
        now = timezone.now()
        found = list(
            asked(request.user).filter(opens_at__lte=now, closes_at__gt=now).order_by("closes_at")[:50]
        )
        return Response(
            MyFeedbackFormSerializer(found, many=True, context=my_context(request.user, found)).data
        )


class MyFeedbackFormView(APIView):
    """GET /feedback-forms/{id}/: a form you were asked to answer, with your answers. PUT
    /feedback-forms/{id}/ saves them: once each, changed as often as you like until it closes."""

    permission_classes = [IsAuthenticated]

    def shown(self, request, form) -> Response:
        return Response(MyFeedbackFormSerializer(form, context=my_context(request.user, [form])).data)

    @extend_schema(responses={200: MyFeedbackFormSerializer})
    def get(self, request, pk):
        return self.shown(request, get_object_or_404(asked(request.user), pk=pk))

    @extend_schema(request=FeedbackAnswersSerializer, responses={200: MyFeedbackFormSerializer})
    def put(self, request, pk):
        body = FeedbackAnswersSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with transaction.atomic():
            recipient = get_object_or_404(
                FeedbackRecipient.objects.select_for_update(of=("self",)).select_related(
                    "form__organization", "form__tournament"
                ),
                form__pk=pk,
                form__status=FeedbackForm.Status.SENT,
                user=request.user,
            )
            form = recipient.form
            now = timezone.now()
            if now < form.opens_at:
                raise ApiException("not_open", "This form isn't open yet.", 409)
            if now >= form.closes_at:
                raise ApiException("form_closed", "This form has closed.", 409)
            answers = service.clean_answers(form, body.validated_data["answers"])
            named = not form.anonymous
            response, made = FeedbackResponse.objects.get_or_create(
                form=form,
                owner_key=service.owner_key(form, request.user),
                defaults={
                    "answers": answers,
                    "respondent": request.user if named else None,
                    "submitted_at": now if named else None,
                    "updated_at": now if named else None,
                },
            )
            if not made:
                response.answers = answers
                response.updated_at = now if named else None
                response.save(update_fields=["answers", "updated_at"])
            if not recipient.answered:
                recipient.answered = True
                recipient.save(update_fields=["answered"])
        return self.shown(request, form)
