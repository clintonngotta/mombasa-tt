import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone

# A guest's address (REQ-003): unique per guest, under a domain that can never receive mail (RFC 2606).
GUEST_EMAIL_DOMAIN = "guests.invalid"


def normalize_email(email: str) -> str:
    return email.strip().lower()


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Users need an email address.")
        user = self.model(email=normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("email_verified_at", timezone.now())
        return self.create_user(email, password, **extra)

    def get_by_natural_key(self, email):
        return self.get(email=normalize_email(email))


class User(AbstractBaseUser, PermissionsMixin):
    """Global login identity. One user is one player across every organization (REQ-003/004)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=80)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    # Optional second way to sign in, in E.164 (accounts/phones.py). Confirmed when the player joined
    # through an invitation link sent to this number; numbers players add themselves are unconfirmed.
    phone = models.CharField(max_length=16, unique=True, null=True, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False, help_text="Django admin access (platform operators only).")
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["display_name"]

    class Meta:
        ordering = ["date_joined"]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        self.email = normalize_email(self.email)
        self.phone = self.phone or None  # blank is no phone, and never clashes with another blank
        super().save(*args, **kwargs)

    @property
    def can_receive_email(self) -> bool:
        """False for a guest entered by club staff: it has no address of its own."""
        return not self.email.endswith("@" + GUEST_EMAIL_DOMAIN)

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def is_verified(self) -> bool:
        """The player proved they hold a way to reach them: a verified email or a confirmed phone."""
        return self.email_verified_at is not None or self.phone_verified_at is not None


# Accounts that may sign in and be entered: a verified email or a confirmed phone (REQ-003).
VERIFIED = models.Q(email_verified_at__isnull=False) | models.Q(phone_verified_at__isnull=False)
