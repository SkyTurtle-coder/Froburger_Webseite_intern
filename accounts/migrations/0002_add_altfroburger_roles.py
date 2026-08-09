from django.db import migrations


NEW_ROLE_CODES = (
    "ALTFROBURGER",
    "AF_KOMITEE",
)


def create_new_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for role_code in NEW_ROLE_CODES:
        Role.objects.get_or_create(code=role_code)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_new_roles, migrations.RunPython.noop),
    ]
