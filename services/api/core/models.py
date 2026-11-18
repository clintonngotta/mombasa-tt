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
