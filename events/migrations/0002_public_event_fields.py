from django.db import migrations, models
from django.template.defaultfilters import slugify


def populate_slugs_and_summaries(apps, schema_editor):
    Event = apps.get_model("events", "Event")
    for event in Event.objects.all().order_by("id"):
        if not event.slug:
            base_slug = slugify(event.title)[:210] or "anlass"
            slug = base_slug
            counter = 2
            while Event.objects.exclude(pk=event.pk).filter(slug=slug).exists():
                slug = f"{base_slug[:210]}-{counter}"
                counter += 1
            event.slug = slug
        if not event.short_description and event.description:
            event.short_description = event.description[:280]
        event.save(update_fields=["slug", "short_description"])


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="is_public",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="event",
            name="short_description",
            field=models.CharField(blank=True, max_length=280),
        ),
        migrations.AddField(
            model_name="event",
            name="slug",
            field=models.SlugField(blank=True, max_length=220, null=True, unique=True),
        ),
        migrations.RunPython(populate_slugs_and_summaries, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="event",
            name="slug",
            field=models.SlugField(blank=True, max_length=220, unique=True),
        ),
    ]
