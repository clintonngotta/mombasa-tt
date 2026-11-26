"""Feedback forms (REQ-055): who is asked, checking answers, totals and the CSV export."""

import csv
import hashlib
import hmac
import io
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from competitions.models import Entry, EntryPlayer
from organizations.models import Membership
from organizations.permissions import Permission, RoleKey
from reservations.models import TournamentUmpire

from .models import FeedbackForm, FeedbackResponse

KINDS = ("rating", "single", "multiple", "short_text", "long_text", "yes_no", "number")
CHOICE_KINDS = ("single", "multiple")
TEXT_LIMIT = {"short_text": 300, "long_text": 3000}
MAX_SECTIONS = 10
MAX_QUESTIONS = 60  # in a whole form
MAX_CHOICES = 12
MAX_RECIPIENTS = 5000
MAX_TEXT_ANSWERS = 500  # shown per question in the totals
NUMBER_LIMIT = Decimal("1000000000")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def stored_sections(sections: list[dict]) -> list[dict]:
    """The sections as stored: every section, question and choice with an id (kept when one was sent,
    made when not or when it repeats)."""
    seen: set[str] = set()

    def keep(given) -> str:
        key = given if given and given not in seen else new_id()
        seen.add(key)
        return key

    stored = []
    for section in sections:
        questions = []
        for question in section.get("questions", []):
            choices = [
                {"id": keep(choice.get("id")), "text": choice["text"]}
                for choice in (question.get("choices") or [])
            ]
            questions.append(
                {
                    "id": keep(question.get("id")),
                    "kind": question["kind"],
                    "text": question["text"],
                    "help": question.get("help", ""),
                    "required": bool(question.get("required", False)),
                    "choices": choices if question["kind"] in CHOICE_KINDS else [],
                }
            )
        stored.append(
            {
                "id": keep(section.get("id")),
                "title": section.get("title", ""),
                "description": section.get("description", ""),
                "questions": questions,
            }
        )
    return stored


def copied_sections(sections: list[dict]) -> list[dict]:
    """A copy with new ids throughout, so a copied form's answers never meet the original's."""

    def strip(section: dict) -> dict:
        questions = [
            {**q, "id": None, "choices": [{"text": c["text"]} for c in q.get("choices", [])]}
            for q in section.get("questions", [])
        ]
        return {**section, "id": None, "questions": questions}

    return stored_sections([strip(section) for section in sections])


def questions(form: FeedbackForm) -> list[dict]:
    return [question for section in form.sections for question in section.get("questions", [])]


def owner_key(form: FeedbackForm, user) -> str:
    """Finds a person's own response without the row naming them: only the server can work it out."""
    message = f"{form.pk}:{user.pk}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def recipient_ids(form: FeedbackForm) -> set:
    """Who a form is for when it is sent: the tournament's accepted players, its umpires, the host's
    competition staff, and the guests named, as chosen on the form."""
    tournament = form.tournament
    people: set = set()
    if form.to_entrants:
        people |= set(
            EntryPlayer.objects.filter(
                entry__event__tournament=tournament, entry__status=Entry.Status.ACCEPTED
            ).values_list("user_id", flat=True)[:MAX_RECIPIENTS]
        )
    if form.to_umpires:
        people |= set(
            TournamentUmpire.objects.filter(tournament=tournament).values_list("user_id", flat=True)
        )
    if form.to_staff:
        people |= set(
            Membership.objects.active()
            .filter(organization=form.organization_id)
            .filter(
                Q(roles__permissions__contains=[Permission.COMPETITIONS_MANAGE.value])
                | Q(roles__key=RoleKey.ADMIN)
            )
            .values_list("user_id", flat=True)
        )
    people |= set(form.guests.values_list("pk", flat=True))
    active = get_user_model().objects.filter(pk__in=people, is_active=True).values_list("pk", flat=True)
    return set(active)


def is_open(form: FeedbackForm, now=None) -> bool:
    now = now or timezone.now()
    return form.status == FeedbackForm.Status.SENT and form.opens_at <= now < form.closes_at


def _number(value) -> str:
    if isinstance(value, bool):
        raise ValueError
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError from error
    if not number.is_finite() or abs(number) > NUMBER_LIMIT:
        raise ValueError
    return format(number.normalize(), "f")


def clean_answers(form: FeedbackForm, given: dict) -> dict:
    """The answers as stored, or a ValidationError naming each question that is wrong: an unknown
    question, the wrong kind of value, a choice the question doesn't offer, a required one left out."""
    if not isinstance(given, dict):
        raise ValidationError({"answers": "Send the answers by question."})  # pragma: no cover
    known = {question["id"]: question for question in questions(form)}
    errors: dict[str, str] = {}
    for key in set(given) - set(known):
        errors[str(key)[:40]] = "This form has no such question."
    cleaned: dict = {}
    for key, question in known.items():
        value = given.get(key)
        kind = question["kind"]
        blank = value is None or value == "" or value == []
        if blank:
            if question["required"]:
                errors[key] = "Answer this question."
            continue
        choices = {choice["id"] for choice in question.get("choices", [])}
        try:
            if kind == "rating":
                if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
                    raise ValueError
                cleaned[key] = value
            elif kind == "yes_no":
                if not isinstance(value, bool):
                    raise ValueError
                cleaned[key] = value
            elif kind == "number":
                cleaned[key] = _number(value)
            elif kind == "single":
                if not isinstance(value, str) or value not in choices:
                    raise ValueError
                cleaned[key] = value
            elif kind == "multiple":
                if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                    raise ValueError
                if not set(value) <= choices or len(set(value)) != len(value):
                    raise ValueError
                cleaned[key] = value
            else:
                if not isinstance(value, str) or len(value.strip()) > TEXT_LIMIT[kind]:
                    raise ValueError
                text = value.strip()
                if not text and question["required"]:
                    errors[key] = "Answer this question."
                elif text:
                    cleaned[key] = text
        except ValueError:
            errors[key] = "That isn't an answer this question takes."
    if errors:
        raise ValidationError(errors)  # one message per question, by its id
    return cleaned


def totals(form: FeedbackForm) -> dict:
    """Per question: how many answered and, by kind, the average and counts, the count per choice, or
    the text answers. Text answers are listed in an order that says nothing about who wrote them."""
    responses = list(form.responses.values_list("answers", flat=True))
    out = []
    for section in form.sections:
        for question in section.get("questions", []):
            key, kind = question["id"], question["kind"]
            values = [answers[key] for answers in responses if key in answers]
            row = {
                "id": key,
                "section": section.get("title", ""),
                "kind": kind,
                "text": question["text"],
                "answered": len(values),
                "average": None,
                "counts": [],
                "texts": [],
            }
            if kind == "rating":
                row["average"] = round(sum(values) / len(values), 2) if values else None
                row["counts"] = [{"label": str(n), "count": values.count(n)} for n in range(1, 6)]
            elif kind == "yes_no":
                row["counts"] = [
                    {"label": "Yes", "count": values.count(True)},
                    {"label": "No", "count": values.count(False)},
                ]
            elif kind == "number":
                numbers = [Decimal(value) for value in values]
                row["average"] = float(round(sum(numbers) / len(numbers), 2)) if numbers else None
            elif kind in CHOICE_KINDS:
                picked = [
                    item for value in values for item in (value if isinstance(value, list) else [value])
                ]
                row["counts"] = [
                    {"label": choice["text"], "count": picked.count(choice["id"])}
                    for choice in question.get("choices", [])
                ]
            else:
                row["texts"] = sorted(values, key=lambda text: hashlib.sha256(text.encode()).digest())[
                    :MAX_TEXT_ANSWERS
                ]
            out.append(row)
    return {"responses": len(responses), "recipients": form.recipients.count(), "questions": out}


def _cell(value) -> str:
    """A spreadsheet runs a cell that starts with one of these as a formula: make it text."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def export_csv(form: FeedbackForm) -> str:
    """One row per response, one column per question. A named form adds who answered and when; an
    anonymous one has neither, and its rows come in an order unrelated to when they were written."""
    asked = questions(form)
    labels = {
        question["id"]: {choice["id"]: choice["text"] for choice in question.get("choices", [])}
        for question in asked
    }
    out = io.StringIO()
    writer = csv.writer(out)
    lead = [] if form.anonymous else ["Name", "Answered"]
    writer.writerow([*lead, *[_cell(question["text"]) for question in asked]])
    responses = FeedbackResponse.objects.filter(form=form).select_related("respondent")
    for response in responses.iterator(chunk_size=500):
        row = []
        if not form.anonymous:
            name = response.respondent.display_name if response.respondent else ""
            answered = response.submitted_at.isoformat(timespec="minutes") if response.submitted_at else ""
            row = [_cell(name), answered]
        for question in asked:
            value = response.answers.get(question["id"])
            if question["kind"] == "single":
                value = labels[question["id"]].get(value, "")
            elif question["kind"] == "multiple":
                value = "; ".join(labels[question["id"]].get(item, "") for item in (value or []))
            elif question["kind"] == "yes_no":
                value = "" if value is None else ("Yes" if value else "No")
            row.append(_cell(value))
        writer.writerow(row)
    return out.getvalue()
