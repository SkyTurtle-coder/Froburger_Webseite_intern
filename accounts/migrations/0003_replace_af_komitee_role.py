from django.db import migrations


NEW_ROLE_CODES = (
    "AF_PRAESIDENT",
    "AF_AKTUAR",
    "AF_KASSIER",
)

ROLE_ASSIGNMENTS = (
    ("Sven", "Cattelan", "AF_PRAESIDENT"),
    ("Benno", "Notter", "AF_AKTUAR"),
    ("Dominik", "Frei", "AF_KASSIER"),
)


def forwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Profile = apps.get_model("accounts", "Profile")

    for role_code in NEW_ROLE_CODES:
        Role.objects.get_or_create(code=role_code)

    old_role = Role.objects.filter(code="AF_KOMITEE").first()
    if old_role is None:
        return

    for first_name, last_name, new_role_code in ROLE_ASSIGNMENTS:
        profile = (
            Profile.objects.filter(first_name=first_name, last_name=last_name, roles=old_role)
            .distinct()
            .first()
        )
        if profile is None:
            continue

        new_role = Role.objects.get(code=new_role_code)
        profile.roles.add(new_role)
        profile.roles.remove(old_role)

    # Remove any remaining legacy assignments before deleting the deprecated role.
    through = Profile.roles.through
    through.objects.filter(role_id=old_role.pk).delete()
    old_role.delete()


def backwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Profile = apps.get_model("accounts", "Profile")

    legacy_role, _created = Role.objects.get_or_create(code="AF_KOMITEE")

    for first_name, last_name, new_role_code in ROLE_ASSIGNMENTS:
        profile = Profile.objects.filter(first_name=first_name, last_name=last_name).first()
        new_role = Role.objects.filter(code=new_role_code).first()
        if profile is None or new_role is None:
            continue

        profile.roles.add(legacy_role)
        profile.roles.remove(new_role)

    Role.objects.filter(code__in=NEW_ROLE_CODES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_add_altfroburger_roles"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
