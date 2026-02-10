from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_branch_latitude_branch_longitude_branch_map_iframe_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='branch',
            name='working_hours',
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
