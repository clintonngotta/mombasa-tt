from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower


class Country(models.Model):
    code = models.CharField(
        primary_key=True,
        max_length=2,
        validators=[RegexValidator(r"^[A-Z]{2}$", "Use a two-letter uppercase country code.")],
    )
    name = models.CharField(max_length=100)
    catalogue_only = models.BooleanField(
        default=False,
        help_text="Use this catalogue as the source of location choices for this country.",
    )

    class Meta:
        ordering = ["name", "code"]
        verbose_name_plural = "countries"

    def __str__(self):
        return self.name


class Region(models.Model):
    country = models.ForeignKey(Country, on_delete=models.PROTECT, related_name="regions")
    name = models.CharField(max_length=100)
    seed_key = models.CharField(max_length=64, unique=True, null=True, editable=False)  # noqa: DJ001 (many unseeded rows)

    class Meta:
        ordering = ["name", "id"]
        constraints = [models.UniqueConstraint(Lower("name"), "country", name="unique_region_in_country")]

    def __str__(self):
        return f"{self.name}, {self.country.name}"


class City(models.Model):
    region = models.ForeignKey(Region, on_delete=models.PROTECT, related_name="cities")
    name = models.CharField(max_length=100)
    seed_key = models.CharField(max_length=64, unique=True, null=True, editable=False)  # noqa: DJ001 (many unseeded rows)

    class Meta:
        ordering = ["name", "id"]
        verbose_name_plural = "cities"
        constraints = [models.UniqueConstraint(Lower("name"), "region", name="unique_city_in_region")]

    def __str__(self):
        return f"{self.name}, {self.region.name}"


class IdempotentRequest(models.Model):
    """A change sent with an Idempotency-Key header, and the answer it got (REQ-013, REQ-035). The app
    keeps changes made offline and sends them when the connection is back. If a reply is lost it sends
    the same change again with the same key, and the server answers from here instead of doing it twice."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    key = models.CharField(max_length=64)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=500)
    # Empty while the first request is still being handled.
    status = models.PositiveSmallIntegerField(null=True)
    body = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint("user", "key", name="unique_idempotency_key_per_user")]

    def __str__(self):
        return f"{self.method} {self.path} ({self.key})"
