import json
from hashlib import sha256
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import City, Country, Region

DATA = Path(__file__).resolve().parents[2] / "data"


class Command(BaseCommand):
    help = "Seed the country list and Kenya's counties and cities without replacing catalogue changes."

    @transaction.atomic
    def handle(self, *args, **options):
        countries = json.loads((DATA / "countries.json").read_text(encoding="utf-8"))
        counties = json.loads((DATA / "kenya.json").read_text(encoding="utf-8"))
        for country in countries:
            code = country["value"]
            Country.objects.get_or_create(
                code=code, defaults={"name": country["label"], "catalogue_only": code == "KE"}
            )
        for county in counties:
            key = sha256(f"KE/{county['name']}".encode()).hexdigest()
            region = Region.objects.filter(seed_key=key).first()
            if region is None:
                region, _ = Region.objects.get_or_create(
                    country_id="KE", name__iexact=county["name"], defaults={"name": county["name"]}
                )
                region.seed_key = key
                region.save(update_fields=["seed_key"])
            for city in county["cities"]:
                city_key = sha256(f"{key}/{city}".encode()).hexdigest()
                if not City.objects.filter(seed_key=city_key).exists():
                    record, _ = City.objects.get_or_create(region=region, name__iexact=city, defaults={"name": city})
                    record.seed_key = city_key
                    record.save(update_fields=["seed_key"])
        self.stdout.write(f"Seeded {len(countries)} countries and {len(counties)} Kenyan counties.")
