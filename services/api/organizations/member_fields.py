"""Custom member fields (REQ-005): which fields a viewer may see, and reading and writing their values.

Two audiences exist. Staff (members.manage) work with every active field of the organization. A member
works only with the member-visible fields of their own membership. Both go through `visible_fields`, so a
staff-only field or value can't reach a member by any route. Retired fields are left out everywhere, but
their values stay in the database.
"""

import math
from datetime import date

from rest_framework.exceptions import ValidationError

from .models import MemberField, MemberFieldValue, Membership, Organization

MAX_ACTIVE_FIELDS = 30
MAX_OPTIONS = 30
MAX_TEXT_LENGTH = 500
MAX_NUMBER = 10**12


def visible_fields(organization: Organization, *, staff: bool):
    """Active fields the viewer may read and write: all of them for staff, member-visible ones otherwise."""
    fields = organization.member_fields.filter(retired_at__isnull=True)
    return fields if staff else fields.filter(visibility=MemberField.Visibility.MEMBER)


def entries(membership: Membership, fields) -> list[dict]:
    """Each of `fields` paired with the membership's value for it (None when unanswered)."""
    fields = list(fields)
    values = dict(membership.field_values.filter(field__in=fields).values_list("field_id", "value"))
    return [{"field": field, "value": values.get(field.id)} for field in fields]


def clean_value(field: MemberField, raw):
    """Normalize a submitted value for `field`. None means "no answer". Raises ValueError with a message
    for the person filling in the form."""
    kind = field.kind
    if isinstance(raw, str):
        raw = raw.strip() or None
    if raw is None:
        if field.required:
            raise ValueError("This field is required.")
        return None
    if kind == MemberField.Kind.TEXT:
        if not isinstance(raw, str):
            raise ValueError("Enter text.")
        if len(raw) > MAX_TEXT_LENGTH:
            raise ValueError(f"Keep this under {MAX_TEXT_LENGTH} characters.")
        return raw
    if kind == MemberField.Kind.NUMBER:
        if isinstance(raw, bool) or not isinstance(raw, int | float) or not math.isfinite(raw):
            raise ValueError("Enter a number.")
        if abs(raw) > MAX_NUMBER:
            raise ValueError("That number is too large.")
        return raw
    if kind == MemberField.Kind.DATE:
        try:
            if not isinstance(raw, str) or len(raw) != 10:
                raise ValueError
            return date.fromisoformat(raw).isoformat()
        except ValueError:
            raise ValueError("Enter a date as YYYY-MM-DD.") from None
    if kind == MemberField.Kind.BOOLEAN:
        if not isinstance(raw, bool):
            raise ValueError("Choose yes or no.")
        return raw
    if raw not in field.options:
        raise ValueError("Choose one of the listed options.")
    return raw


def write_values(membership: Membership, fields, submitted: dict, actor) -> None:
    """Apply `submitted` ({field id: value}) to the membership. Only `fields` can be written; any other
    id (retired, another organization's, or hidden from this viewer) is rejected without saying which.
    Nothing is saved unless every value is valid. Call inside a transaction."""
    by_id = {str(field.id): field for field in fields}
    if set(submitted) - set(by_id):
        raise ValidationError({"values": "One or more fields don't exist here."})
    cleaned, errors = {}, {}
    for field_id, raw in submitted.items():
        try:
            cleaned[field_id] = clean_value(by_id[field_id], raw)
        except ValueError as error:
            errors[field_id] = str(error)
    if errors:
        raise ValidationError(errors)
    for field_id, value in cleaned.items():
        if value is None:
            MemberFieldValue.objects.filter(membership=membership, field=by_id[field_id]).delete()
        else:
            MemberFieldValue.objects.update_or_create(
                membership=membership, field=by_id[field_id], defaults={"value": value, "updated_by": actor}
            )
