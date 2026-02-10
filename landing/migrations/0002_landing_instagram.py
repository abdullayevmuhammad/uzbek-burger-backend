from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('landing', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='landingsettings',
            name='instagram',
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
