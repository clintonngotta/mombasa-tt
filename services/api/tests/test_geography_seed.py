"""The location catalogue seeder (TASK-093)."""

from django.core.management import call_command

from core.models import City, Country, Region


def test_seeding_fills_the_catalogue_once_and_keeps_platform_edits(db):
    call_command("seed_geography", stdout=None)
    kenya = Country.objects.get(pk="KE")
    assert kenya.catalogue_only
    assert Region.objects.filter(country=kenya).count() == 47
    assert Country.objects.filter(catalogue_only=False).count() > 100
    cities = City.objects.count()

    # A super admin renames a county and a town, and adds one of their own.
    mombasa = Region.objects.get(country=kenya, name="Mombasa")
    mombasa.name = "Mombasa County"
    mombasa.save()
    town = City.objects.filter(region=mombasa).first()
    town.name = f"{town.name} Island"
    town.save()
    City.objects.create(region=mombasa, name="Shanzu")

    call_command("seed_geography", stdout=None)
    assert Region.objects.filter(country=kenya).count() == 47
    assert Region.objects.filter(country=kenya, name="Mombasa").count() == 0
    assert City.objects.count() == cities + 1
    assert City.objects.filter(pk=town.pk, name__endswith=" Island").exists()
