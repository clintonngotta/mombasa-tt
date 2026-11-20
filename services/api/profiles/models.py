from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models


class PlayerProfile(models.Model):
    """Self-described player details (REQ-006). The display name lives on User because it is the
    global identity; everything here is private except what the directory deliberately shows."""

    class Hand(models.TextChoices):
        RIGHT = "right"
        LEFT = "left"

    class Grip(models.TextChoices):
        SHAKEHAND = "shakehand"
        PENHOLD = "penhold"
        OTHER = "other"

    class Experience(models.TextChoices):
        NEW = "new"
        CASUAL = "casual"
        CLUB = "club"
        COMPETITIVE = "competitive"

    class Goal(models.TextChoices):
        COMPETE = "compete"
        RATING = "rating"
        TRAIN = "train"
        FIND_CLUB = "find_club"
        UMPIRE = "umpire"
        ORGANIZE = "organize"

    class Detail(models.TextChoices):
        """Extended details a player may publish on their directory page (REQ-006)."""

        HAND = "hand"
        GRIP = "grip"
        STYLE = "style"
        EXPERIENCE = "experience"
        BIO = "bio"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True, related_name="profile"
    )
    nickname = models.CharField(max_length=40, blank=True)
    hand = models.CharField(max_length=10, choices=Hand.choices, blank=True)
    grip = models.CharField(max_length=10, choices=Grip.choices, blank=True)
    style = models.CharField(max_length=80, blank=True)
    experience = models.CharField(max_length=12, choices=Experience.choices, blank=True)
    bio = models.CharField(max_length=280, blank=True)
    country = models.CharField(max_length=2, blank=True)
    region = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    # Shown to the player, and to other signed-in players only while directory_opt_in is on.
    avatar = models.OneToOneField(
        "attachments.Attachment", null=True, blank=True, on_delete=models.SET_NULL, related_name="avatar_of"
    )
    # Off by default: a player appears in the directory only after opting in.
    directory_opt_in = models.BooleanField(default=False)
    # Extended details stay private until named here, and show only while directory_opt_in is on.
    published_details = ArrayField(
        models.CharField(max_length=12, choices=Detail.choices), default=list, blank=True
    )
    # Goals only order Home shortcuts. They never grant roles or touch ratings.
    goals = ArrayField(models.CharField(max_length=12, choices=Goal.choices), default=list, blank=True)
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile of {self.user_id}"


def profile_for(user) -> PlayerProfile:
    profile, _ = PlayerProfile.objects.get_or_create(user=user)
    return profile


def listed_profiles():
    """Profiles other players may be shown (REQ-006): opted in to the directory and still active. The one
    place this rule lives; the directory, player pages and photo access all start from it."""
    return PlayerProfile.objects.filter(directory_opt_in=True, user__is_active=True)
