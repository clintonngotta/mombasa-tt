from io import BytesIO

from django.utils import timezone
from PIL import Image

from accounts.models import User

from .conftest import PASSWORD, BrowserClient


def make_user(email, **extra):
    extra.setdefault("display_name", email.split("@")[0])
    return User.objects.create_user(email=email, password=PASSWORD, email_verified_at=timezone.now(), **extra)


def make_official(user, country: str, region: str = "", *, role="official"):
    """Make the user an official (TASK-107): an active member of the region's body, or of the country's
    national body when no region is given, holding the body's Official role (or `role`, a RoleKey). The
    body is created if missing. Returns the body."""
    from organizations.models import Membership, Organization, seed_roles

    kind = Organization.Kind.REGIONAL_BODY if region else Organization.Kind.NATIONAL_BODY
    body = Organization.objects.filter(kind=kind, country=country, region__iexact=region).first()
    if body is None:
        place = region or country
        body = Organization.objects.create(
            name=f"{place} body", town=place, country=country, region=region, kind=kind
        )
        seed_roles(body)
    membership, _ = Membership.objects.get_or_create(organization=body, user=user)
    if role:
        membership.roles.add(body.roles.get(key=role))
    return body


def logged_in(user):
    client = BrowserClient()
    response = client.post("/api/v1/auth/login/", {"email": user.email, "password": PASSWORD}, format="json")
    assert response.status_code == 200
    return client


def image_upload(fmt="JPEG", size=(900, 600), name="me.jpg", **save) -> BytesIO:
    """An in-memory image file ready to post as a multipart upload."""
    out = BytesIO()
    Image.new("RGB", size, "navy").save(out, fmt, **save)
    out.seek(0)
    out.name = name
    return out
