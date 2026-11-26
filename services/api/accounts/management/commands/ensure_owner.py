"""The platform owner's account, made when the API starts (deployment.md, "The owner account").

OWNER_EMAIL and OWNER_PASSWORD come from the environment. With neither set this does nothing. The account
is a platform super admin with a verified email, so the owner can sign in at once and reach everything.
The password is used only to create the account: later starts never reset it, so a password the owner
changes in the app stays changed. The password is never printed.
"""

import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User, normalize_email


class Command(BaseCommand):
    help = "Create the platform owner from OWNER_EMAIL and OWNER_PASSWORD, or restore their authority."

    def handle(self, *args, **options):
        email = os.environ.get("OWNER_EMAIL", "").strip()
        password = os.environ.get("OWNER_PASSWORD", "")
        name = os.environ.get("OWNER_NAME", "").strip()[:80] or "Platform owner"
        if not email and not password:
            self.stdout.write("OWNER_EMAIL is not set: no owner account was made.")
            return
        if not email or not password:
            raise CommandError("Set OWNER_EMAIL and OWNER_PASSWORD together, or neither.")
        try:
            validate_email(email)
        except ValidationError as error:
            raise CommandError("OWNER_EMAIL is not an email address.") from error
        email = normalize_email(email)

        try:
            with transaction.atomic():
                owner = User.objects.select_for_update().filter(email=email).first()
                if owner is None:
                    candidate = User(email=email, display_name=name)
                    try:
                        validate_password(password, candidate)
                    except ValidationError as error:
                        raise CommandError(
                            "OWNER_PASSWORD is too weak: " + " ".join(error.messages)
                        ) from error
                    User.objects.create_superuser(email, password, display_name=name)
                    self.stdout.write("Owner account created.")
                    return
                changed = []
                for field in ("is_active", "is_staff", "is_superuser"):
                    if not getattr(owner, field):
                        setattr(owner, field, True)
                        changed.append(field)
                if owner.email_verified_at is None:
                    owner.email_verified_at = timezone.now()
                    changed.append("email_verified_at")
                if changed:
                    owner.save(update_fields=changed)
                    self.stdout.write("Owner account restored: " + ", ".join(changed) + ".")
                else:
                    self.stdout.write("Owner account is in place.")
        except IntegrityError:
            # Another process starting at the same moment made it first.
            self.stdout.write("Owner account is in place.")
