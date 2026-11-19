from django.db import migrations


def load(apps, schema_editor):
    from training.standard_drills import STANDARD_DRILLS

    Drill = apps.get_model("training", "Drill")
    for drill in STANDARD_DRILLS:
        fields = {key: value for key, value in drill.items() if key != "id"}
        Drill.objects.update_or_create(id=drill["id"], defaults={**fields, "owner": None, "organization": None})


def unload(apps, schema_editor):
    from training.standard_drills import STANDARD_DRILLS

    apps.get_model("training", "Drill").objects.filter(id__in=[d["id"] for d in STANDARD_DRILLS]).delete()


class Migration(migrations.Migration):
    dependencies = [("training", "0002_drill_patterns_and_club_plans")]

    operations = [migrations.RunPython(load, unload)]
