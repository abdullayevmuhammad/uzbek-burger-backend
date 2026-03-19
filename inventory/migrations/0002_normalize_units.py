from decimal import Decimal, ROUND_HALF_UP
from django.db import migrations


def normalize_units(apps, schema_editor):
    # Runtime normalisation is handled in services (to_base/from_base) without
    # mutating historical data to avoid double-scaling live numbers.
    return


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0001_initial"),
        ("menu", "0002_setitem"),
        ("catalog", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(normalize_units, migrations.RunPython.noop),
    ]
