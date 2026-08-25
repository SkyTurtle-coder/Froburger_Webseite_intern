from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0012_profile_avatar_icon"),
    ]

    operations = [
        migrations.AlterField(
            model_name="profile",
            name="avatar_icon",
            field=models.CharField(
                blank=True,
                choices=[
                    ("bursch_f", "Bursch (F)"),
                    ("bursch_m", "Bursch (M)"),
                    ("fux_f", "Fux (F)"),
                    ("fux_m", "Fux (M)"),
                    ("fuxmajor_f", "Fuxmajor (F)"),
                    ("fuxmajor_m", "Fuxmajor (M)"),
                ],
                max_length=16,
            ),
        ),
    ]
