"""Give every tournament a public link slug: added empty, filled from each name and year, then required."""

from django.db import migrations, models
from django.utils.text import slugify


def fill_slugs(apps, schema_editor):
    Tournament = apps.get_model("competitions", "Tournament")
    used = set()
    for tournament in Tournament.objects.order_by("created_at", "id").only("id", "name", "starts_on"):
        base = slugify(tournament.name)[:60].strip("-") or "tournament"
        year = str(tournament.starts_on.year)
        if year not in base.split("-"):
            base = f"{base}-{year}"
        slug, n = base, 1
        while slug in used:
            n += 1
            slug = f"{base}-{n}"
        used.add(slug)
        Tournament.objects.filter(pk=tournament.pk).update(slug=slug)


class Migration(migrations.Migration):
    dependencies = [("competitions", "0027_match_time_set")]

    operations = [
        migrations.AddField(
            model_name="tournament",
            name="slug",
            field=models.SlugField(max_length=80, null=True, editable=False, db_index=False),
        ),
        migrations.RunPython(fill_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="tournament",
            name="slug",
            # Unique but nullable: the previous release creates tournaments without a slug until it is
            # replaced, and the next save gives them one.
            field=models.SlugField(max_length=80, unique=True, null=True, editable=False),
        ),
    ]
