import uuid

from django.db import migrations


def anonymize_usernames(apps, schema_editor):
    User = apps.get_model("auth", "User")

    # First free all existing names so a prior `mitglied-<id>` cannot collide.
    for user in User.objects.order_by("pk").iterator():
        User.objects.filter(pk=user.pk).update(username=f"__migration_{uuid.uuid4().hex}")

    for user in User.objects.order_by("pk").iterator():
        User.objects.filter(pk=user.pk).update(username=f"mitglied-{user.pk}")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0014_add_ehrenphilister_role"),
    ]

    operations = [
        migrations.RunPython(anonymize_usernames, migrations.RunPython.noop),
    ]
