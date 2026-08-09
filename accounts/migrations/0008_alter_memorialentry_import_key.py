from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0007_memorialentry_import_key"),
    ]

    operations = [
        migrations.AlterField(
            model_name="memorialentry",
            name="import_key",
            field=models.CharField(blank=True, max_length=64, unique=True, verbose_name="Import-Schlüssel"),
        ),
    ]
