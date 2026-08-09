from django.db import migrations, models


def set_homepage_flag_for_existing_public_events(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    Event.objects.filter(is_public=True).exclude(status="INTERN").update(show_on_homepage=True)


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0002_public_event_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="show_on_homepage",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(set_homepage_flag_for_existing_public_events, migrations.RunPython.noop),
    ]
