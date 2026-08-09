from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0008_alter_memorialentry_import_key"),
    ]

    operations = [
        migrations.AlterField(
            model_name="memorialentry",
            name="import_key",
            field=models.CharField(blank=True, max_length=64, null=True, unique=True, verbose_name="Import-Schlüssel"),
        ),
    ]
