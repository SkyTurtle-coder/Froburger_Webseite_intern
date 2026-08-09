from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_profile_membership_fields_and_memorialentry"),
    ]

    operations = [
        migrations.AddField(
            model_name="memorialentry",
            name="import_key",
            field=models.CharField(blank=True, max_length=80, unique=True, verbose_name="Import-Schlüssel"),
        ),
    ]
