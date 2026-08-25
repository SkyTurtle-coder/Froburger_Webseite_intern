from django.db import migrations, models

from accounts.roles import ROLE_CHOICES


NEW_ROLE_CODES = (
    "AF_BEISITZER",
    "AF_TOTENFEIERN",
)


def create_new_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for role_code in NEW_ROLE_CODES:
        Role.objects.get_or_create(code=role_code)


def delete_new_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.filter(code__in=NEW_ROLE_CODES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0010_memorialentry_obituary_document"),
    ]

    operations = [
        migrations.AlterField(
            model_name="role",
            name="code",
            field=models.CharField(choices=ROLE_CHOICES, max_length=32, unique=True),
        ),
        migrations.RunPython(create_new_roles, delete_new_roles),
    ]
