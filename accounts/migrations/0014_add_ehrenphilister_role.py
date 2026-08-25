from django.db import migrations, models

from accounts.roles import ROLE_CHOICES


def add_ehrenphilister_role(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.get_or_create(code="EHRENPHILISTER")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0013_alter_profile_avatar_icon"),
    ]

    operations = [
        migrations.AlterField(
            model_name="role",
            name="code",
            field=models.CharField(choices=ROLE_CHOICES, max_length=32, unique=True),
        ),
        migrations.RunPython(add_ehrenphilister_role, migrations.RunPython.noop),
    ]
