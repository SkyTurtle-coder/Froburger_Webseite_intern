from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0011_add_additional_af_roles"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="avatar_icon",
            field=models.CharField(
                blank=True,
                choices=[
                    ("bursch_f", "Bursch (F)"),
                    ("bursch_m", "Bursch (M)"),
                    ("fux_f", "Fux (F)"),
                    ("fux_m", "Fux (M)"),
                ],
                max_length=16,
            ),
        ),
    ]
